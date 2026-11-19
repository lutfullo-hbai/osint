"""orginfo.uz — a public directory of Uzbek legal entities built from the state
statistics register (stat.uz): for each company its head (rahbar), founders
(ta'sischilar) with shares, STIR, address and official contacts.

It is a third-party aggregator, not the register itself, and its data can lag
(each page says "current as of <date>"), so every result is marked as medium
reliability and links to the page it came from (ROADMAP 7.4).

Used on demand: one search page plus a few organisation pages per query, at
most one request per second, cached for a week. robots.txt allows these
paths (/search/ and /organization/; /api/ is not used).
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
import time
from urllib.parse import quote

import httpx

from cache import get_cached_json, set_cached_json
from services.names import names_match
from tools.base import ToolError
from tools.hub_domains import is_hub_domain

BASE = "https://orginfo.uz"
USER_AGENT = "osint-tool/1.0 (self-hosted research; on-demand lookups)"
TIMEOUT = httpx.Timeout(15.0)
MIN_INTERVAL_SECONDS = 1.0
CACHE_TTL_SECONDS = 7 * 24 * 3600
MAX_PEOPLE_HITS = 8
MAX_ORG_DETAILS = 3
MAX_COMPANY_PIVOTS = 3      # a common name has many same-name directors
RELIABILITY = ("Reliability: medium (orginfo.uz is a third-party copy of the stat.uz register "
               "and may be out of date; confirm on stat.uz or my.gov.uz)")
ROLES = {"managers": "head (rahbar)", "founders": "founder (ta'sischi)"}

_lock = asyncio.Lock()
_last_call = 0.0
_APOSTROPHES = re.compile("[ʻʼ’‘'´]")
_CARD_RE = re.compile(
    r'<a href="/uz/organization/([0-9a-f]{8,16})/"[^>]*og-card.*?</a>', re.DOTALL)
_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


async def _get_page(path: str) -> str:
    """One page, rate-limited and cached."""
    global _last_call
    key = "osint:orginfo:" + hashlib.sha256(path.encode()).hexdigest()
    cached = await get_cached_json(key)
    if cached is not None:
        return cached["html"]
    async with _lock:
        wait = _last_call + MIN_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT},
                                         follow_redirects=True) as client:
                response = await client.get(BASE + path)
        except httpx.HTTPError as exc:
            raise ToolError(f"orginfo.uz unreachable ({type(exc).__name__})") from exc
        finally:
            _last_call = time.monotonic()
    if response.status_code != 200:
        raise ToolError(f"orginfo.uz returned HTTP {response.status_code}")
    page = response.text[:2_000_000]
    await set_cached_json(key, {"html": page}, CACHE_TTL_SECONDS)
    return page


def register_spelling(name: str) -> str:
    """The register writes names upper-case with a backtick for the Uzbek
    apostrophe: "Ro'ziqulov" -> "RO`ZIQULOV"."""
    return " ".join(_APOSTROPHES.sub("`", name).upper().split())


def parse_cards(page: str) -> list[dict]:
    """Organisation cards on a search page: id, STIR, registration date, name, person."""
    cards = []
    for match in _CARD_RE.finditer(page):
        block = match.group(0)
        stir = re.search(r"rounded-5\">\s*(\d{9})\s*<", block)
        date = re.search(r"calendar\">\s*([\d.]{10})", block)
        title = re.search(r'card-title">(.*?)</h6>', block, re.DOTALL)
        person = re.search(r'tab_managers\.svg" alt="[^"]*">(.*?)</p>', block, re.DOTALL)
        cards.append({
            "id": match.group(1),
            "stir": stir.group(1) if stir else "",
            "registered": date.group(1) if date else "",
            "name": _text(title.group(1)) if title else "",
            "person": _text(person.group(1)) if person else "",
        })
    return cards


def parse_organization(page: str) -> dict | None:
    """The schema.org Organization block of an organisation page."""
    for raw in _LD_RE.findall(page):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for block in data if isinstance(data, list) else [data]:
            entity = block.get("mainEntity") if isinstance(block, dict) else None
            if isinstance(entity, dict) and entity.get("@type") == "Organization":
                entity = dict(entity)
                entity["as_of"] = str(block.get("dateModified") or "")[:10]
                return entity
    return None


# a founder can be another company, which the page still marks as a person
_COMPANY_MARKERS = re.compile(r'["«»]|\b(?:MCHJ|MChJ|AJ|XK|QK|OK|XAJ|DUK|LLC|LTD|INC|OOO|ООО|АО|GMBH|JSC|'
                              r'KORXONASI|FIRMASI|HOLDING|GROUP|BANK|UNITARY)\b', re.IGNORECASE)


def is_company_name(name: str) -> bool:
    return bool(_COMPANY_MARKERS.search(name or ""))


def display_name(name: str) -> str:
    """"RO`ZIQULOV SHOHRUH" -> "Ro`ziqulov Shohruh" (str.title() would give "Ro`Ziqulov")."""
    return " ".join(w[:1].upper() + w[1:].lower() for w in str(name).split())


def _people(entity: dict) -> tuple[list[str], list[str]]:
    heads = entity.get("employee") or []
    heads = heads if isinstance(heads, list) else [heads]
    founders = entity.get("founder") or []
    founders = founders if isinstance(founders, list) else [founders]
    names = lambda items: [str(p.get("name") or "").strip() for p in items  # noqa: E731
                           if isinstance(p, dict) and p.get("@type") == "Person" and p.get("name")]
    return names(heads), names(founders)


def org_result(org_id: str, entity: dict) -> tuple[dict, list[dict]]:
    """A company search result plus its pivots: the people (name) and the website."""
    heads, founders = _people(entity)
    address = entity.get("address") or {}
    parts = [f"Organisation: {entity.get('alternateName') or entity.get('name') or ''}".strip()]
    if entity.get("taxID"):
        parts.append(f"STIR: {entity['taxID']}")
    for label, value in (
        ("Head", ", ".join(heads)),
        ("Founders", ", ".join(founders[:5])),
        ("Registered", entity.get("foundingDate")),
        ("Address", ", ".join(v for v in (address.get("addressLocality"), address.get("streetAddress")) if v)),
        ("E-mail", entity.get("email")),
        ("Phone", entity.get("telephone")),
        ("Website", entity.get("url")),
        ("Data as of", entity.get("as_of")),
    ):
        if value:
            parts.append(f"{label}: {str(value)[:200]}")
    parts.append(RELIABILITY)
    pivots = [{"type": "name", "value": display_name(person), "via": "official_register"}
              for person in (heads + founders)[:4] if len(person.split()) >= 2 and not is_company_name(person)]
    site = re.sub(r"^https?://", "", str(entity.get("url") or "").strip().lower()).split("/")[0]
    site = site.removeprefix("www.")
    if site and "." in site and not is_hub_domain(site) and site != "orginfo.uz":
        pivots.append({"type": "domain", "value": site, "via": "official_register"})
    return {
        "platform": "orginfo.uz — company register copy",
        "url": f"{BASE}/uz/organization/{org_id}/",
        "status": "found",
        "source": "uz_register",
        "reliability": "medium",
        "info": "; ".join(parts),
    }, pivots


async def lookup_company(query: str) -> dict:
    """Company search: matching organisations with their head and founders."""
    page = await _get_page(f"/uz/search/organizations/?q={quote(query)}")
    results, pivots = [], []
    for card in parse_cards(page)[:MAX_ORG_DETAILS]:
        try:
            entity = parse_organization(await _get_page(f"/uz/organization/{card['id']}/"))
        except ToolError:
            entity = None
        if not entity:
            entity = {"name": card["name"], "taxID": card["stir"], "foundingDate": card["registered"]}
        result, found = org_result(card["id"], entity)
        results.append(result)
        pivots.extend(found)
    return {"results": results, "pivots": pivots}


async def lookup_person(name: str) -> dict:
    """Name search: companies where a same-name person is the head or a founder.

    orginfo.uz matches loosely (Shohruh also finds Shoxrux, Xoliqulov), so
    only entries whose name really matches the query are kept.
    """
    query = register_spelling(name)
    results, pivots, seen = [], [], set()
    for role, role_label in ROLES.items():
        page = await _get_page(f"/uz/search/{role}/?q={quote(query)}")
        for card in parse_cards(page):
            if not card["person"] or not names_match(name, card["person"]):
                continue
            key = (role, card["id"])
            if key in seen:
                continue
            seen.add(key)
            parts = [f"Person: {card['person']} — {role_label}",
                     f"Organisation: {card['name']}"]
            if card["stir"]:
                parts.append(f"STIR: {card['stir']}")
            if card["registered"]:
                parts.append(f"Registered: {card['registered']}")
            parts += ["A same-name entry in the company register; confirm it is the same person",
                      RELIABILITY]
            results.append({
                "platform": f"orginfo.uz — company {role_label.split(' ')[0]}",
                "url": f"{BASE}/uz/organization/{card['id']}/",
                "status": "found",
                "source": "uz_register",
                "reliability": "medium",
                "info": "; ".join(parts),
            })
            if card["stir"] and len(pivots) < MAX_COMPANY_PIVOTS:
                pivots.append({"type": "company", "value": card["stir"], "via": "official_register"})
            if len(results) >= MAX_PEOPLE_HITS:
                return {"results": results, "pivots": pivots}
    return {"results": results, "pivots": pivots}
