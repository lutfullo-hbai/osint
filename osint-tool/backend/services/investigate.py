import asyncio
import hashlib
import ipaddress
import re
from urllib.parse import urlparse

import httpx

from cache import DEFAULT_TTL_SECONDS, get_cached_json, set_cached_json
from tools.base import ToolError
from tools.domain_enrich import (
    http_fingerprint,
    tls_lookup,
    urlscan_lookup,
    wayback_lookup,
)
from tools.domain_intel import (
    DEFAULT_TIMEOUT,
    DomainValidationError,
    dns_lookup,
    ip_geo_lookup,
    normalize_domain,
    rdap_lookup,
    subdomain_lookup,
)
from tools.email_domain import domain_mail_intel, email_domain_intel, gravatar_lookup
from tools.email_intel import lookup_emailrep, lookup_hibp
from tools.holehe_runner import run_holehe
from tools.image_intel import analyze_image, fetch_image_bytes
from tools.ip_intel import internetdb_lookup, rdap_ip_lookup, reverse_dns_lookup
from tools.net_guard import UnsafeURLError, is_public_ip
from tools.maigret_runner import run_maigret
from tools.entity_intel import run_person_entity, run_sanctions_check
from tools.name_search import run_name_search, run_username_web
from tools.phone_intel import PhoneParseError, analyze
from tools.public_profiles import manual_links, run_name_sources, run_profile_sources
from tools.public_search import filter_results_containing, search_public
from tools.sherlock_runner import run_sherlock
from tools.truecaller import TruecallerUnavailable, pick_region, scrape_truecaller


class InvestigationValidationError(ValueError):
    pass


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-().]{5,18}[0-9]$")
ALLOWED_NAME_PUNCTUATION = set(" '-.")
USERNAME_MIN_LENGTH = 2
USERNAME_MAX_LENGTH = 64
ALLOWED_USERNAME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)
CLASSIFIEDS_BATCH = "(site:olx.uz OR site:torg.uz OR site:avito.ru OR site:myshop.uz)"

CACHE_TTL = DEFAULT_TTL_SECONDS
MAX_PIVOTS = 15
ENGINE_SOURCES = {"sherlock", "maigret"}
CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
USERNAME_NOTICE = (
    "A matching username on two sites does not prove they belong to the same "
    "person. Confirm with independent evidence."
)
NAME_NOTICE = (
    "Results match a name, not a person: different people often share one. "
    "Confirm with independent evidence."
)


def normalize_name(raw_name: str) -> str:
    name = re.sub(r"\s+", " ", raw_name.strip())
    if not (3 <= len(name) <= 80):
        raise InvestigationValidationError(
            "Name must be between 3 and 80 characters."
        )
    letter_count = sum(1 for char in name if char.isalpha())
    if letter_count < 2:
        raise InvestigationValidationError(
            "Name must contain at least two letters."
        )
    if not all(
        char.isalpha() or char in ALLOWED_NAME_PUNCTUATION for char in name
    ):
        raise InvestigationValidationError(
            "Name may only contain letters, spaces, apostrophes, "
            "hyphens and dots."
        )
    return name


def normalize_username(raw_username: str) -> str:
    username = raw_username.strip().lstrip("@")
    if not (
        USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH
    ) or not set(username) <= ALLOWED_USERNAME_CHARS:
        raise InvestigationValidationError(
            "Username must be 2-64 characters and contain only letters, digits, "
            "dots, underscores or hyphens."
        )
    return username


def normalize_email(raw_email: str) -> str:
    email = raw_email.strip().lower()
    if not EMAIL_RE.fullmatch(email):
        raise InvestigationValidationError(
            "Please provide a valid email address."
        )
    return email


def normalize_phone(raw_query: str) -> str:
    query = raw_query.strip()
    if not PHONE_RE.fullmatch(query):
        raise InvestigationValidationError(
            "Please provide a valid phone number, e.g. +998901234567."
        )
    return query


def normalize_domain_query(raw_query: str) -> str:
    try:
        return normalize_domain(raw_query)
    except DomainValidationError as exc:
        raise InvestigationValidationError(str(exc)) from exc


def normalize_image_url(raw_url: str) -> str:
    url = raw_url.strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise InvestigationValidationError(
            "Please provide a valid http(s) image URL, e.g. "
            "https://example.com/photo.jpg."
        )
    return url


async def _cached(key: str, producer, *args) -> dict:
    cached = await get_cached_json(key)
    if cached is not None:
        cached["cached"] = True
        return cached

    result = await producer(*args)
    if result.get("status") == "success":
        await set_cached_json(key, result, CACHE_TTL)
    return result


async def _collect(lookups: dict) -> tuple[dict, list[str]]:
    """Run lookups concurrently so one failing source cannot sink the others."""
    labels = list(lookups)
    outcomes = await asyncio.gather(*lookups.values(), return_exceptions=True)

    succeeded = {}
    warnings = []
    for label, outcome in zip(labels, outcomes):
        if isinstance(outcome, ToolError):
            warnings.append(f"{label}: {outcome}")
        elif isinstance(outcome, BaseException):
            warnings.append(f"{label} failed unexpectedly: {type(outcome).__name__}")
        else:
            succeeded[label] = outcome
    return succeeded, warnings


async def _investigate_name(name: str) -> dict:
    outcomes, warnings = await _collect(
        {
            "Web search": run_name_search(name),
            "Public sources": run_name_sources(name),
            "Knowledge base": run_person_entity(name),
            "Sanctions": run_sanctions_check(name),
        }
    )
    if not outcomes:
        raise ToolError("All lookups failed: " + "; ".join(warnings))

    results = []
    pivots = []
    # Knowledge-base identity (Wikidata/Wikipedia) first: it is the most
    # authoritative when the person is notable.
    if "Knowledge base" in outcomes:
        results.extend(outcomes["Knowledge base"]["results"])
        pivots.extend(outcomes["Knowledge base"]["pivots"])
    if "Sanctions" in outcomes:
        results.extend(outcomes["Sanctions"]["results"])
        warnings.extend(outcomes["Sanctions"]["warnings"])
    if "Public sources" in outcomes:
        sources = outcomes["Public sources"]
        results.extend(sources["results"])
        pivots.extend(sources["pivots"])
        warnings.extend(sources["warnings"])
    if "Web search" in outcomes:
        search = outcomes["Web search"]
        results.extend(search["results"])
        if search["dropped"]:
            warnings.append(
                f"{search['dropped']} search result(s) filtered out: the name "
                "was not actually in them."
            )

    response = {
        "status": "success",
        "query": name,
        "results": results,
        "count": len(results),
        "notice": NAME_NOTICE,
    }
    if pivots:
        response["pivots"] = pivots
    if warnings:
        response["warnings"] = warnings
    if not results:
        response["message"] = (
            "No publicly indexed profiles found for this exact name. "
            "Try quoting a nickname instead of the full name."
        )
    return response


async def investigate_name(raw_name: str) -> dict:
    name = normalize_name(raw_name)
    return await _cached(f"osint:name:{name.casefold()}", _investigate_name, name)


def _describe(tool_name: str, exc: BaseException) -> str:
    if isinstance(exc, ToolError):
        return f"{tool_name}: {exc}"
    return f"{tool_name}: unexpected error: {exc}"


def _profile_key(url: str, platform: str) -> str:
    """Sherlock and Maigret format the same profile URL differently."""
    if not url:
        return platform.lower()
    return re.sub(r"^https?://(www\.)?", "", url.lower()).rstrip("/")


def _confidence(sources: list[str]) -> str:
    engines = [source for source in sources if source in ENGINE_SOURCES]
    if "public-api" in sources or len(engines) > 1:
        return "high"
    return "medium" if engines else "low"


def _merge(
    sherlock_results: list[dict],
    maigret_results: list[dict],
    direct: list[dict] = (),
    indexed: list[dict] = (),
) -> list[dict]:
    merged = {}
    # Direct API entries go first so their richer details win over bare hits.
    ordered_entries = (
        [("public-api", entry) for entry in direct]
        + [("sherlock", entry) for entry in sherlock_results]
        + [("maigret", entry) for entry in maigret_results]
        + [("search-index", entry) for entry in indexed]
    )
    for source, entry in ordered_entries:
        key = _profile_key(entry["url"], entry["platform"])
        if key in merged:
            if source not in merged[key]["sources"]:
                merged[key]["sources"].append(source)
        else:
            merged[key] = {
                "platform": entry["platform"],
                "url": entry["url"],
                "status": entry["status"],
                "sources": [source],
                **({"info": entry["info"]} if entry.get("info") else {}),
            }
    # Confidence says the account exists, not who owns it.
    for item in merged.values():
        item["confidence"] = _confidence(item["sources"])
    return sorted(
        merged.values(),
        key=lambda item: (
            CONFIDENCE_ORDER[item["confidence"]],
            item["platform"].lower(),
        ),
    )


async def _investigate_username(username: str) -> dict:
    outcomes, warnings = await _collect(
        {
            "Sherlock": run_sherlock(username),
            "Maigret": run_maigret(username),
            "Public profiles": run_profile_sources(username),
            "Web search": run_username_web(username),
        }
    )
    failed = list(warnings)

    def results_of(label: str) -> list[dict]:
        return outcomes[label]["results"] if label in outcomes else []

    results = _merge(
        results_of("Sherlock"),
        results_of("Maigret"),
        direct=results_of("Public profiles"),
        indexed=results_of("Web search"),
    )
    if not results and failed:
        raise ToolError("; ".join(failed))

    pivots = []
    seen_pivots = set()

    def add_pivots(new_pivots):
        for pivot in new_pivots:
            key = (pivot["type"], pivot["value"].casefold())
            if key not in seen_pivots:
                seen_pivots.add(key)
                pivots.append(pivot)

    if "Public profiles" in outcomes:
        warnings.extend(outcomes["Public profiles"]["warnings"])
        add_pivots(outcomes["Public profiles"]["pivots"])

    posts = []
    if "Web search" in outcomes:
        posts = outcomes["Web search"]["posts"]
        add_pivots(outcomes["Web search"]["pivots"])

    seen_platforms = {item["platform"] for item in results}
    response = {
        "status": "success",
        "query": username,
        "results": results,
        "count": len(results),
        "notice": USERNAME_NOTICE,
        "links": [
            link for link in manual_links(username)
            if link["label"] not in seen_platforms
        ],
    }
    if posts:
        response["posts"] = posts
    if pivots:
        response["pivots"] = pivots
    if warnings:
        response["warnings"] = warnings
    return response


async def investigate_username(raw_username: str) -> dict:
    username = normalize_username(raw_username)
    return await _cached(
        f"osint:username:{username.casefold()}", _investigate_username, username
    )


async def _investigate_email(email: str) -> dict:
    lookups = {
        "Holehe": run_holehe(email),
        "EmailRep": lookup_emailrep(email),
        "HIBP": lookup_hibp(email),
        "Email domain checks": email_domain_intel(email),
        "Gravatar": gravatar_lookup(email),
        "Public mentions": search_public([f'"{email}"'], max_results_per_batch=10),
    }
    expected_lookups = len(lookups)
    outcomes, warnings = await _collect(lookups)

    results = []
    if "Holehe" in outcomes:
        results.extend(outcomes["Holehe"]["results"])
    if "EmailRep" in outcomes:
        results.append(outcomes["EmailRep"])
    if "HIBP" in outcomes:
        hibp_entry, hibp_warning = outcomes["HIBP"]
        if hibp_entry:
            results.append(hibp_entry)
        if hibp_warning:
            warnings.append(hibp_warning)
    if "Email domain checks" in outcomes:
        domain_results, domain_warnings = outcomes["Email domain checks"]
        results.extend(domain_results)
        warnings.extend(domain_warnings)
    if outcomes.get("Gravatar"):
        results.append(outcomes["Gravatar"])
    # Search engines ignore quotes, so keep only pages that really show the address.
    results.extend(
        item
        for item in outcomes.get("Public mentions", [])
        if email in f"{item.get('title')} {item.get('info')}".lower()
    )

    if not results and len(outcomes) < expected_lookups:
        raise ToolError("All lookups failed: " + "; ".join(warnings))

    response = {
        "status": "success",
        "query": email,
        "results": results,
        "count": len(results),
        "pivots": [{"type": "domain", "value": email.rsplit("@", 1)[-1]}],
    }
    if warnings:
        response["warnings"] = warnings
    return response


async def investigate_email(raw_email: str) -> dict:
    email = normalize_email(raw_email)
    return await _cached(f"osint:email:{email}", _investigate_email, email)


async def _investigate_phone(raw_query: str) -> dict:
    warnings = []
    results = []

    try:
        meta = analyze(raw_query)
    except PhoneParseError as exc:
        raise InvestigationValidationError(str(exc)) from exc

    e164 = meta["e164"]
    results.append(
        {
            "platform": "Telecom info",
            "name": meta["international"],
            "url": "",
            "status": "found",
            "info": meta["info"],
        }
    )

    region = pick_region(e164)
    try:
        outcome = await scrape_truecaller(e164, region)
        if outcome["name"]:
            entry = {
                "platform": "Truecaller",
                "name": outcome["name"],
                "status": "found",
                "profile_url": outcome["profile_url"],
            }
            if outcome["info"]:
                entry["info"] = outcome["info"]
            results.append(entry)
        else:
            warnings.append(
                "Truecaller page loaded but no public owner information is "
                "visible without authentication."
            )
    except TruecallerUnavailable as exc:
        warnings.append(str(exc))
    except Exception as exc:
        warnings.append(f"Truecaller lookup failed unexpectedly: {exc}")

    digits = re.sub(r"\D", "", e164)
    batches = [
        f'"{digits}"',
        f'"{digits}" {CLASSIFIEDS_BATCH}',
        f'"{meta["national"]}"',
    ]
    try:
        mentions = await search_public(batches, max_results_per_batch=10)
        mentions, dropped = await filter_results_containing(
            mentions, [digits, meta["national_number"]]
        )
        results.extend(mentions)
        if dropped:
            warnings.append(
                f"{dropped} page(s) filtered out: the number was not actually "
                "found in their content."
            )
    except ToolError as exc:
        warnings.append(f"Public mentions search failed: {exc}")

    response = {
        "status": "success",
        "query": raw_query,
        "results": results,
        "count": len(results),
    }
    if warnings:
        response["warnings"] = warnings
    return response


async def investigate_phone(raw_query: str) -> dict:
    query = normalize_phone(raw_query)
    digits = re.sub(r"\D", "", query)
    return await _cached(f"osint:phone:{digits}", _investigate_phone, query)


def _pivots(ips: list[str], domains: list[str]) -> list[dict]:
    pivots = [{"type": "ip", "value": ip} for ip in ips if ip]
    pivots += [{"type": "domain", "value": name} for name in domains[:MAX_PIVOTS]]
    return pivots


async def _investigate_domain(domain: str) -> dict:
    async with httpx.AsyncClient(
        headers={"User-Agent": "osint-tool/1.0"},
        follow_redirects=True,
        timeout=DEFAULT_TIMEOUT,
    ) as client:
        outcomes, warnings = await _collect(
            {
                "RDAP": rdap_lookup(client, domain),
                "Subdomains": subdomain_lookup(client, domain),
                "urlscan.io": urlscan_lookup(client, domain),
                "Wayback Machine": wayback_lookup(client, domain),
                "HTTP fingerprint": http_fingerprint(client, domain),
                "TLS": tls_lookup(domain),
                "Mail": domain_mail_intel(domain),
                "DNS": dns_lookup(domain),
            }
        )

        results: list[dict] = []
        for label in ("RDAP", "urlscan.io", "Wayback Machine", "HTTP fingerprint", "TLS"):
            if label in outcomes:
                results.append(outcomes[label])

        subdomains: list[str] = []
        if "Subdomains" in outcomes:
            entry, subdomains, subdomain_warnings = outcomes["Subdomains"]
            results.append(entry)
            warnings.extend(f"Subdomains: {w}" for w in subdomain_warnings)

        if "Mail" in outcomes:
            mail_results, mail_warnings = outcomes["Mail"]
            results.extend(mail_results)
            warnings.extend(mail_warnings)

        first_ip = ""
        if "DNS" in outcomes:
            dns_entry, first_ip = outcomes["DNS"]
            results.append(dns_entry)
            if first_ip:
                try:
                    results.append(await ip_geo_lookup(client, first_ip))
                except ToolError as exc:
                    warnings.append(f"IP geolocation: {exc}")

    if not results:
        raise ToolError("All lookups failed: " + "; ".join(warnings))

    response = {
        "status": "success",
        "category": "domain",
        "query": domain,
        "results": results,
        "count": len(results),
        "pivots": _pivots([first_ip], subdomains),
    }
    if warnings:
        response["warnings"] = warnings
    return response


async def _investigate_ip(ip_address: str) -> dict:
    async with httpx.AsyncClient(
        headers={"User-Agent": "osint-tool/1.0"},
        follow_redirects=True,
        timeout=DEFAULT_TIMEOUT,
    ) as client:
        outcomes, warnings = await _collect(
            {
                "Reverse DNS": reverse_dns_lookup(ip_address),
                "RDAP": rdap_ip_lookup(client, ip_address),
                "IP geolocation": ip_geo_lookup(client, ip_address),
                "Shodan InternetDB": internetdb_lookup(client, ip_address),
            }
        )

    results: list[dict] = []
    hostnames: set[str] = set()
    for label in ("RDAP", "IP geolocation"):
        if label in outcomes:
            results.append(outcomes[label])
    for label in ("Reverse DNS", "Shodan InternetDB"):
        if label in outcomes:
            entry, names = outcomes[label]
            results.append(entry)
            hostnames.update(names)

    if not results:
        raise ToolError("All lookups failed: " + "; ".join(warnings))

    response = {
        "status": "success",
        "category": "domain",
        "query": ip_address,
        "results": results,
        "count": len(results),
        "pivots": _pivots([], sorted(hostnames)),
    }
    if warnings:
        response["warnings"] = warnings
    return response


def parse_ip_query(raw_query: str) -> str | None:
    """Return a public IP, None if the query is not an IP, or reject a private one."""
    candidate = raw_query.strip()
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if not is_public_ip(candidate):
        raise InvestigationValidationError(
            "Private, loopback and reserved IP addresses have no public intel."
        )
    return candidate


async def investigate_domain(raw_query: str) -> dict:
    ip_address = parse_ip_query(raw_query)
    if ip_address:
        return await _cached(f"osint:ip:{ip_address}", _investigate_ip, ip_address)
    domain = normalize_domain_query(raw_query)
    return await _cached(
        f"osint:domain:{domain}", _investigate_domain, domain
    )


async def _investigate_image(url: str) -> dict:
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": "osint-tool/1.0 (local self-audit)"},
            follow_redirects=False,
            timeout=httpx.Timeout(20.0),
        ) as client:
            data, _content_type, final_url = await fetch_image_bytes(client, url)
    except UnsafeURLError as exc:
        raise InvestigationValidationError(str(exc)) from exc

    outcome = analyze_image(data, final_url)
    results = outcome["results"]
    response = {
        "status": "success",
        "query": url,
        "results": results,
        "count": len(results),
    }
    if outcome["warnings"]:
        response["warnings"] = outcome["warnings"]
    return response


async def investigate_image(raw_url: str) -> dict:
    url = normalize_image_url(raw_url)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return await _cached(f"osint:image:{digest}", _investigate_image, url)


HANDLERS = {
    "name": investigate_name,
    "username": investigate_username,
    "email": investigate_email,
    "phone": investigate_phone,
    "domain": investigate_domain,
    "image": investigate_image,
}

CATEGORIES = tuple(sorted(HANDLERS))


async def investigate(category: str, query: str) -> dict:
    normalized_category = category.strip().lower()
    handler = HANDLERS.get(normalized_category)
    if handler is None:
        raise InvestigationValidationError(
            f"Unknown category '{category}'. Choose one of: "
            + ", ".join(CATEGORIES)
            + "."
        )
    return await handler(query)
