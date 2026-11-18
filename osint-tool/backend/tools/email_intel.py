import asyncio
import os
import re

import httpx
from xposedornot import XposedOrNot
from xposedornot.exceptions import NotFoundError, RateLimitError, XposedOrNotError

from tools.base import ToolError

HTTP_HEADERS = {"User-Agent": "osint-tool/1.0 (local self-audit)"}


async def lookup_emailrep(email: str) -> dict:
    async with httpx.AsyncClient(headers=HTTP_HEADERS, timeout=20) as client:
        response = await client.get(f"https://emailrep.io/{email}")
    if response.status_code == 429:
        raise ToolError("EmailRep rate limit reached for this IP.")
    if response.status_code != 200:
        raise ToolError(f"EmailRep returned HTTP {response.status_code}.")
    data = response.json()

    info_parts = [f"Reputation: {data.get('reputation', 'unknown')}"]
    if "suspicious" in data:
        info_parts.append(f"Suspicious: {'yes' if data['suspicious'] else 'no'}")
    if "references" in data and data["references"] is not None:
        info_parts.append(f"References: {data['references']}")

    details = data.get("details") or {}
    if details.get("credentials_leaked"):
        info_parts.append("Credentials leaked: yes")
    if details.get("data_breach"):
        info_parts.append("Seen in data breaches: yes")
    if details.get("profiles"):
        profiles = details["profiles"]
        if profiles:
            info_parts.append(f"Public profiles on: {', '.join(profiles[:6])}")

    return {
        "platform": "EmailRep",
        "url": f"https://emailrep.io/{email}",
        "status": "found",
        "info": "; ".join(info_parts),
    }


async def lookup_hibp(email: str) -> tuple[dict | None, str | None]:
    api_key = os.environ.get("HIBP_API_KEY", "").strip()
    if not api_key:
        return None, (
            "HIBP breach check skipped: set the HIBP_API_KEY environment "
            "variable to enable it (https://haveibeenpwned.com/API/Key)."
        )
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.get(
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}"
            "?truncateResponse=false",
            headers={"hibp-api-key": api_key, **HTTP_HEADERS},
        )
    if response.status_code == 404:
        return {
            "platform": "HIBP Breaches",
            "url": "https://haveibeenpwned.com/",
            "status": "found",
            "info": "No known breaches contain this email. Good news.",
        }, None
    if response.status_code == 401:
        raise ToolError("HIBP rejected the API key (HTTP 401).")
    if response.status_code == 429:
        raise ToolError("HIBP rate limit reached. Retry later.")
    if response.status_code != 200:
        raise ToolError(f"HIBP returned HTTP {response.status_code}.")

    breaches = response.json()
    names = []
    for breach in breaches[:8]:
        name = breach.get("Name", "Unknown")
        date = breach.get("BreachDate", "")
        names.append(f"{name} ({date})" if date else name)
    more = len(breaches) - len(names)
    summary = ", ".join(names)
    if more > 0:
        summary += f" +{more} more"
    return {
        "platform": "HIBP Breaches",
        "url": "https://haveibeenpwned.com/",
        "status": "found",
        "info": f"Found in {len(breaches)} breach(es): {summary}",
    }, None


def _summarize_breaches(names: list[str], limit: int = 8) -> str:
    shown = ", ".join(names[:limit])
    more = len(names) - limit
    return shown + (f" +{more} more" if more > 0 else "")


HIBP_CATALOG_URL = "https://haveibeenpwned.com/api/v3/breaches"   # free, no key
CATALOG_CACHE_KEY = "osint:hibp:catalog"
CATALOG_TTL = 24 * 3600
_SENSITIVE_CLASSES = ("Passwords", "Password hints", "Phone numbers", "Physical addresses",
                      "Dates of birth", "Security questions and answers", "Credit cards",
                      "Bank account numbers", "Government issued IDs")


def _norm_breach(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


async def breach_catalog() -> dict[str, dict]:
    """HIBP's public breach catalogue (metadata only, no personal data), cached a day."""
    from cache import get_cached_json, set_cached_json

    cached = await get_cached_json(CATALOG_CACHE_KEY)
    if cached is not None:
        return cached
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0),
                                 headers={"User-Agent": "osint-tool/1.0 (breach catalogue)"}) as client:
        response = await client.get(HIBP_CATALOG_URL)
    if response.status_code != 200:
        raise ToolError(f"HIBP catalogue HTTP {response.status_code}")
    catalog = {}
    for b in response.json():
        entry = {"title": b.get("Title") or b.get("Name"), "date": b.get("BreachDate", ""),
                 "classes": b.get("DataClasses") or [], "count": b.get("PwnCount") or 0,
                 "domain": b.get("Domain") or ""}
        for key in {_norm_breach(b.get("Name")), _norm_breach(b.get("Title"))} - {""}:
            catalog[key] = entry
    await set_cached_json(CATALOG_CACHE_KEY, catalog, CATALOG_TTL)
    return catalog


def describe_breaches(names: list[str], catalog: dict[str, dict], limit: int = 8) -> str:
    """'Adobe (2013-10-04: Email addresses, Passwords, ...)' + exposed-data summary."""
    parts, sensitive = [], set()
    for name in names[:limit]:
        meta = catalog.get(_norm_breach(name))
        if meta:
            classes = ", ".join(meta["classes"][:4]) + ("…" if len(meta["classes"]) > 4 else "")
            parts.append(f"{meta['title']} ({meta['date']}: {classes})")
            sensitive |= {c for c in meta["classes"] if c in _SENSITIVE_CLASSES}
        else:
            parts.append(name)
    for name in names[limit:]:
        meta = catalog.get(_norm_breach(name))
        if meta:
            sensitive |= {c for c in meta["classes"] if c in _SENSITIVE_CLASSES}
    text = ", ".join(parts) + (f" +{len(names) - limit} more" if len(names) > limit else "")
    if sensitive:
        text += ". Sensitive data types exposed across these breaches: " + ", ".join(sorted(sensitive))
    return text


def _xposedornot_check(email: str) -> list[str]:
    # The official SDK is synchronous (httpx.Client + time.sleep backoff on
    # 429), so it runs in a worker thread; see lookup_xposedornot.
    with XposedOrNot(timeout=20) as client:
        return list(client.check_email(email).breaches)


async def lookup_xposedornot(email: str) -> dict:
    """Free breach check (no key) via the official XposedOrNot SDK."""
    try:
        breaches = await asyncio.to_thread(_xposedornot_check, email)
    except NotFoundError:
        breaches = []
    except RateLimitError:
        raise ToolError("XposedOrNot rate limit reached. Retry later.") from None
    except XposedOrNotError as exc:
        raise ToolError(f"XposedOrNot lookup failed: {exc}") from None

    if not breaches:
        info = "No known breaches contain this email (XposedOrNot)."
    else:
        try:
            catalog = await breach_catalog()
        except (ToolError, httpx.HTTPError, ValueError):
            catalog = {}      # enrichment is optional; the names still stand
        info = (
            f"Found in {len(breaches)} breach(es): {describe_breaches(breaches, catalog)}"
            + (". Breach dates and data types: HIBP public catalogue." if catalog else "")
        )
    return {
        "platform": "XposedOrNot Breaches",
        "url": "https://xposedornot.com/",
        "status": "found",
        "info": info,
    }


async def lookup_breaches(email: str) -> tuple[dict | None, str | None]:
    """Breach check: HIBP when HIBP_API_KEY is set, otherwise free XposedOrNot.

    Returns (entry, warning) like lookup_hibp. The "No known breaches" phrase in
    the no-hit message is relied on by the footprint exposure score.
    """
    if os.environ.get("HIBP_API_KEY", "").strip():
        return await lookup_hibp(email)
    return await lookup_xposedornot(email), None
