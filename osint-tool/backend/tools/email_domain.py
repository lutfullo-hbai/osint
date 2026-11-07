import asyncio
import hashlib
import re
import time

import httpx

RESOLVER_TIMEOUT = 5
# Selectors big mail providers and platforms commonly publish DKIM under.
DKIM_SELECTORS = (
    "google", "selector1", "selector2", "default", "k1", "s1", "s2",
    "dkim", "mail", "mandrill", "mailjet", "sendgrid", "zoho", "amazonses",
)
DISPOSABLE_URL = (
    "https://raw.githubusercontent.com/disposable-email-domains/"
    "disposable-email-domains/master/disposable_email_blocklist.conf"
)
_DISPOSABLE_CACHE: dict = {"domains": None, "fetched": 0.0}
_DISPOSABLE_TTL = 86400
_disposable_lock = asyncio.Lock()
GRAVATAR_URL = "https://www.gravatar.com/avatar/{digest}?d=404&s=200"


def _txt_records(resolver, name: str) -> list[str]:
    records = []
    try:
        answers = resolver.resolve(name, "TXT", lifetime=RESOLVER_TIMEOUT)
    except Exception:
        return records
    for answer in answers:
        try:
            records.append(b"".join(answer.strings).decode("utf-8", "ignore"))
        except Exception:
            records.append(str(answer).strip('"'))
    return records


def _is_valid_dkim(record: str) -> bool:
    """A real DKIM selector has a non-empty public key. Reject null/wildcard keys."""
    match = re.search(r"p=([A-Za-z0-9+/=]*)", record)
    if not match:
        return False
    # Empty p= is a revoked/placeholder key (e.g. wildcard "v=DKIM1; p=").
    return len(match.group(1)) >= 20


def gather_dns_records(domain: str) -> dict:
    import dns.resolver

    resolver = dns.resolver.Resolver()
    resolver.lifetime = RESOLVER_TIMEOUT
    resolver.timeout = RESOLVER_TIMEOUT

    mx_records = []
    try:
        answers = resolver.resolve(domain, "MX", lifetime=RESOLVER_TIMEOUT)
        mx_records = [str(answer.exchange).rstrip(".") for answer in answers]
    except Exception:
        pass

    dkim_selectors = []
    for selector in DKIM_SELECTORS:
        for record in _txt_records(resolver, f"{selector}._domainkey.{domain}"):
            if _is_valid_dkim(record):
                dkim_selectors.append(selector)
                break

    return {
        "mx": mx_records,
        "txt": _txt_records(resolver, domain),
        "dmarc": _txt_records(resolver, f"_dmarc.{domain}"),
        "dkim": dkim_selectors,
    }


def summarize_auth(records: dict) -> tuple[list[dict], list[str]]:
    results: list[dict] = []
    warnings: list[str] = []

    mx_records = records.get("mx") or []
    if mx_records:
        results.append(
            {
                "platform": "MX records",
                "status": "found",
                "info": ", ".join(mx_records[:6]),
            }
        )
    else:
        warnings.append(
            "No MX records found - this domain may not receive email."
        )

    txt_records = records.get("txt") or []
    dmarc_records = records.get("dmarc") or []
    spf = next(
        (record for record in txt_records if record.lower().startswith("v=spf1")),
        "",
    )
    dmarc = next(
        (record for record in dmarc_records if record.lower().startswith("v=dmarc1")),
        "",
    )

    dkim_selectors = records.get("dkim") or []
    auth_parts = [
        f"SPF: {'yes' if spf else 'no'}",
        f"DMARC: {'yes' if dmarc else 'no'}",
        f"DKIM: {'yes (' + ', '.join(dkim_selectors) + ')' if dkim_selectors else 'none found'}",
    ]
    if spf:
        auth_parts.append(f"SPF policy: {spf[:160]}")
    if dmarc:
        auth_parts.append(f"DMARC policy: {dmarc[:160]}")
    results.append(
        {
            "platform": "Email authentication",
            "status": "found",
            "info": " | ".join(auth_parts),
        }
    )

    if not spf:
        warnings.append("No SPF record found - sender spoofing may be easier.")
    if not dmarc:
        warnings.append("No DMARC record found - domain has no DMARC policy.")
    if not dkim_selectors:
        warnings.append(
            "No DKIM selector found among common names (it may use a custom one)."
        )

    return results, warnings


async def domain_mail_intel(domain: str) -> tuple[list[dict], list[str]]:
    records = await asyncio.to_thread(gather_dns_records, domain)
    return summarize_auth(records)


async def load_disposable_domains() -> set[str]:
    now = time.monotonic()
    if (
        _DISPOSABLE_CACHE["domains"] is not None
        and now - _DISPOSABLE_CACHE["fetched"] < _DISPOSABLE_TTL
    ):
        return _DISPOSABLE_CACHE["domains"]
    async with _disposable_lock:
        if (
            _DISPOSABLE_CACHE["domains"] is not None
            and now - _DISPOSABLE_CACHE["fetched"] < _DISPOSABLE_TTL
        ):
            return _DISPOSABLE_CACHE["domains"]
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(DISPOSABLE_URL)
        domains = {
            line.strip().lower() for line in response.text.split() if line.strip()
        }
        _DISPOSABLE_CACHE["domains"] = domains
        _DISPOSABLE_CACHE["fetched"] = now
        return domains


async def disposable_check(domain: str) -> dict | None:
    try:
        domains = await load_disposable_domains()
    except Exception:
        return None
    if domain.lower() in domains:
        return {
            "platform": "Disposable email",
            "status": "found",
            "info": (
                "This domain is a known disposable / throwaway email provider. "
                "Treat the address as temporary and low-trust."
            ),
        }
    return None


async def email_domain_intel(email: str) -> tuple[list[dict], list[str]]:
    domain = email.rsplit("@", 1)[-1].lower()
    results, warnings = await domain_mail_intel(domain)
    disposable = await disposable_check(domain)
    if disposable:
        results.append(disposable)
        warnings.append("Disposable email domain.")
    return results, warnings


# Gravatar accounts map to a username pivot on these platforms.
GRAVATAR_PIVOT_SERVICES = {"twitter", "github", "instagram", "tiktok", "telegram"}


def parse_gravatar_profile(entry: dict, image_url: str) -> tuple[dict, list[dict]]:
    fields = []
    for label, key in (
        ("Name", "displayName"),
        ("Location", "currentLocation"),
        ("Job", "job_title"),
        ("Company", "company"),
        ("Pronouns", "pronouns"),
    ):
        value = entry.get(key)
        if value:
            fields.append(f"{label}: {value}")
    about = (entry.get("aboutMe") or "").strip()
    if about:
        fields.append(f"About: {about[:200]}")

    pivots = []
    account_notes = []
    for account in entry.get("accounts") or []:
        shortname = str(account.get("shortname") or "").lower()
        username = account.get("username") or account.get("display") or ""
        url = account.get("url") or ""
        account_notes.append(f"{account.get('name') or shortname}: {url or username}")
        if shortname in GRAVATAR_PIVOT_SERVICES and username:
            pivots.append({"type": "username", "value": username})
    if account_notes:
        fields.append("Linked accounts: " + "; ".join(account_notes[:8]))

    entry_out = {
        "platform": "Gravatar profile",
        "url": entry.get("profileUrl") or image_url,
        "status": "found",
        "title": entry.get("displayName") or "",
        "info": "; ".join(fields) or "A public Gravatar profile exists for this email.",
    }
    return entry_out, pivots


async def gravatar_lookup(email: str) -> dict:
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
    image_url = GRAVATAR_URL.format(digest=digest)
    async with httpx.AsyncClient(
        timeout=10, follow_redirects=True, headers={"User-Agent": "osint-tool/1.0"}
    ) as client:
        response = await client.get(f"https://gravatar.com/{digest}.json")
        if response.status_code == 404:
            # No profile, but an avatar may still be registered (d=404 probe).
            avatar = await client.get(image_url, params={"d": "404"})
            if avatar.status_code == 200:
                return {
                    "results": [{
                        "platform": "Gravatar",
                        "url": image_url,
                        "status": "found",
                        "info": "A public Gravatar image is registered for this email.",
                    }],
                    "pivots": [],
                }
            return {"results": [], "pivots": []}
        if response.status_code != 200:
            return {"results": [], "pivots": []}

    try:
        entry = response.json()["entry"][0]
    except (ValueError, KeyError, IndexError):
        return {"results": [], "pivots": []}
    result, pivots = parse_gravatar_profile(entry, image_url)
    return {"results": [result], "pivots": pivots}
