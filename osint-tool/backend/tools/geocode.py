"""Place names <-> coordinates via OpenStreetMap Nominatim (free).

Nominatim's usage policy: an identifying User-Agent, at most 1 request per
second, cache results, no bulk geocoding. One investigation needs a handful of
lookups, so we serialise calls, space them 1.1 s apart and cache for 30 days.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time

import httpx

from cache import get_cached_json, set_cached_json

NOMINATIM = "https://nominatim.openstreetmap.org"
USER_AGENT = "osint-tool/1.0 (self-hosted research tool; low volume)"
MIN_INTERVAL_SECONDS = 1.1
CACHE_TTL_SECONDS = 30 * 24 * 3600
TIMEOUT = httpx.Timeout(15.0)

_lock = asyncio.Lock()
_last_call = 0.0


async def _get(path: str, params: dict):
    global _last_call
    key = "osint:geocode:" + hashlib.sha256(
        (path + json.dumps(params, sort_keys=True)).encode()
    ).hexdigest()
    cached = await get_cached_json(key)
    if cached is not None:
        return cached
    async with _lock:
        wait = _last_call + MIN_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
                response = await client.get(f"{NOMINATIM}{path}", params={**params, "format": "jsonv2"})
        finally:
            _last_call = time.monotonic()
    if response.status_code != 200:
        return None
    data = response.json()
    await set_cached_json(key, data, CACHE_TTL_SECONDS)
    return data


async def search(query: str, country_codes: list[str] | None = None, limit: int = 3) -> list[dict]:
    """Free-text place search -> [{lat, lon, label, kind, importance, bbox}]."""
    query = " ".join(str(query or "").split())[:200]
    if len(query) < 2:
        return []
    params = {"q": query, "limit": limit, "addressdetails": 0, "accept-language": "en"}
    if country_codes:
        params["countrycodes"] = ",".join(c.lower() for c in country_codes if len(c) == 2)
    data = await _get("/search", params) or []
    out = []
    for row in data:
        try:
            bbox = [float(x) for x in row.get("boundingbox") or []]
            out.append({
                "lat": float(row["lat"]), "lon": float(row["lon"]),
                "label": row.get("display_name", ""),
                "kind": f"{row.get('category', '')}:{row.get('type', '')}",
                "importance": float(row.get("importance") or 0),
                "bbox": bbox,
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def reverse(lat: float, lon: float, zoom: int = 10) -> dict | None:
    """Coordinates -> {label, country, country_code, city}."""
    data = await _get("/reverse", {"lat": round(lat, 4), "lon": round(lon, 4), "zoom": zoom,
                                   "addressdetails": 1, "accept-language": "en"})
    if not data or "error" in data:
        return None
    address = data.get("address") or {}
    return {
        "label": data.get("display_name", ""),
        "country": address.get("country", ""),
        "country_code": (address.get("country_code") or "").upper(),
        "city": address.get("city") or address.get("town") or address.get("village")
                or address.get("county") or address.get("state") or "",
    }
