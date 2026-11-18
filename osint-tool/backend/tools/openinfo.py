"""openinfo.uz — the official corporate-disclosure portal for Uzbek joint-stock
companies and other issuers (operated for the capital-market regulator).

Issuers must disclose their management, so a record gives the director,
chief accountant and responsible officer, plus STIR, address, e-mail, website,
exchange ticker and status. Used on demand only (one search + a few detail
pages per company query), cached, at most one request per second; robots.txt
allows these API paths. Nothing is bulk-copied.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time

import httpx

from cache import get_cached_json, set_cached_json
from tools.base import ToolError
from tools.hub_domains import is_hub_domain
from tools.name_search import transliterate

BASE = "https://openinfo.uz"
USER_AGENT = "osint-tool/1.0 (self-hosted research; on-demand lookups)"
TIMEOUT = httpx.Timeout(15.0)
MIN_INTERVAL_SECONDS = 1.0
CACHE_TTL_SECONDS = 7 * 24 * 3600
MAX_ORGS = 3

_lock = asyncio.Lock()
_last_call = 0.0
_APOSTROPHES = re.compile("[ʻʼ’‘`´]")


async def _get(path: str, params: dict | None = None):
    global _last_call
    key = "osint:openinfo:" + hashlib.sha256(f"{path}?{sorted((params or {}).items())}".encode()).hexdigest()
    cached = await get_cached_json(key)
    if cached is not None:
        return cached
    async with _lock:
        wait = _last_call + MIN_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
                response = await client.get(f"{BASE}{path}", params=params)
        except httpx.HTTPError as exc:
            raise ToolError(f"openinfo.uz unreachable ({type(exc).__name__})") from exc
        finally:
            _last_call = time.monotonic()
    if response.status_code != 200:
        raise ToolError(f"openinfo.uz returned HTTP {response.status_code}")
    data = response.json()
    await set_cached_json(key, data, CACHE_TTL_SECONDS)
    return data


def query_variants(query: str) -> list[str]:
    """The portal matches Uzbek-Latin substrings: try the Latin spelling too."""
    query = " ".join(str(query or "").split())
    variants = [query, _APOSTROPHES.sub("'", query)]
    if re.search("[а-яёўқғҳА-ЯЁЎҚҒҲ]", query):
        latin = transliterate(query)
        if latin:
            # title-casing makes "O'Zbek...": the letter after o'/g' stays lower
            variants.append(re.sub(r"'([A-Z])", lambda m: "'" + m.group(1).lower(), latin))
    seen, out = set(), []
    for v in variants:
        if v and v.casefold() not in seen:
            seen.add(v.casefold())
            out.append(v)
    return out


async def search(query: str) -> list[dict]:
    for variant in query_variants(query):
        data = await _get("/api/v2/organizations/organizations/", {"search": variant, "page_size": MAX_ORGS})
        results = (data or {}).get("results") or []
        if results:
            return results[:MAX_ORGS]
    return []


def to_result(org: dict) -> tuple[dict, list[dict]]:
    detail = org.get("detailinfo") or {}
    parts = [f"Organisation: {org.get('full_name_text') or org.get('short_name_text') or ''}"]
    if org.get("inn"):
        parts.append(f"STIR: {org['inn']}")
    if org.get("exchange_ticket_name"):
        parts.append(f"Ticker: {org['exchange_ticket_name']}")
    for label, value in (
        ("Director", detail.get("director_name")),
        ("Chief accountant", detail.get("accountant_name")),
        ("Disclosure officer", detail.get("responsible_officer_name")),
        ("Address", org.get("address") or org.get("location")),
        ("E-mail", org.get("email")),
        ("Website", org.get("web_site")),
        ("Status", org.get("status_from_stat_uz")),
    ):
        if value:
            parts.append(f"{label}: {str(value)[:160]}")
    parts.append("Source: the company's own legally required disclosure")
    pivots = []
    site = str(org.get("web_site") or "").strip().lower()
    site = re.sub(r"^https?://", "", site).split("/")[0].removeprefix("www.")
    if site and "." in site and not is_hub_domain(site):
        pivots.append({"type": "domain", "value": site, "via": "official_register"})
    return {
        "platform": "openinfo.uz — corporate disclosure",
        "url": f"{BASE}/ru/organizations/{org.get('id')}",
        "status": "found",
        "source": "uz_register",
        "info": "; ".join(parts),
    }, pivots


async def lookup(query: str) -> dict:
    """Search, then fetch the detail page (management) of the best matches."""
    found = await search(query)
    results, pivots = [], []
    for org in found:
        try:
            detail = await _get(f"/api/v2/organizations/organizations/{int(org['id'])}/")
        except (ToolError, KeyError, ValueError, TypeError):
            detail = org
        result, org_pivots = to_result(detail or org)
        results.append(result)
        pivots.extend(org_pivots)
    return {"results": results, "pivots": pivots}
