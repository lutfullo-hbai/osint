"""Image geolocation: where was this photo taken?

Pipeline (all free, self-hosted):
1. EXIF GPS — exact when the camera recorded it.
2. OCR (English, Russian, Uzbek Latin/Cyrillic) — shop names, street signs,
   phone codes and web domains that point at a country or a business.
3. GeoCLIP (internal container) — likely GPS points from the pixels alone.
4. A local vision model (run from the browser, like AI Summary) lists visible
   clues and place names; `refine()` geocodes them with OpenStreetMap.
5. Fusion — candidates from independent sources that agree reinforce each
   other; the result is a ranked list of places with their evidence, never a
   single "answer".

Only the PLACE is estimated. Nothing here identifies people in the photo.
"""
from __future__ import annotations

import asyncio
import math
import os
import re

import httpx

from tools import geocode
from tools.base import ToolError
from tools.image_intel import analyze_image, geo_links

GEOCLIP_URL = os.environ.get("GEOCLIP_URL", "").strip().rstrip("/")
GEOCLIP_TIMEOUT = httpx.Timeout(120.0, connect=5.0)
GEOCLIP_TOP_K = 5
MAX_VISION_PLACES = 6
NOTICE = (
    "Estimated locations with their evidence — verify before relying on them. "
    "This finds places, not people: do not use it to track or locate a person."
)

# How precise a geocoded place of each kind is (search radius in metres) and
# how much a vision-model place of that kind is worth before agreement.
KIND_RADIUS = {
    "exif": 30, "business": 300, "landmark": 300, "street": 800, "district": 3000,
    "city": 15000, "region": 150000, "country": 600000,
}
KIND_WEIGHT = {
    "business": 0.75, "landmark": 0.8, "street": 0.6, "district": 0.5,
    "city": 0.5, "region": 0.3, "country": 0.2,
}

# Phone prefixes and ccTLDs that, seen in OCR text, hint at a country.
PHONE_HINTS = {"+998": "UZ", "+996": "KG", "+992": "TJ", "+993": "TM", "+994": "AZ",
               "+7": "RU/KZ", "+90": "TR", "+971": "AE", "+82": "KR", "+44": "GB", "+1": "US/CA"}
TLD_HINTS = {".uz": "UZ", ".kg": "KG", ".tj": "TJ", ".kz": "KZ", ".ru": "RU", ".tr": "TR",
             ".ae": "AE", ".kr": "KR", ".de": "DE", ".uk": "GB"}


def haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def text_hints(text: str) -> list[dict]:
    """Country hints from phone prefixes and domains visible in the image."""
    hints = []
    compact = re.sub(r"[\s()\-]", "", text or "")
    for prefix, country in sorted(PHONE_HINTS.items(), key=lambda kv: -len(kv[0])):
        if re.search(re.escape(prefix) + r"\d{6,}", compact):
            hints.append({"country": country, "evidence": f"phone number with {prefix}"})
            break
    lowered = (text or "").lower()
    for tld, country in TLD_HINTS.items():
        if re.search(r"[a-z0-9-]+" + re.escape(tld) + r"\b", lowered):
            hints.append({"country": country, "evidence": f"web address ending in {tld}"})
    return hints


def _candidate(lat, lon, radius_m, source, score, evidence, label=""):
    return {"lat": round(lat, 6), "lon": round(lon, 6), "radius_m": int(radius_m),
            "label": label, "score": round(score, 3), "sources": [source], "evidence": list(evidence)}


async def _geoclip(data: bytes) -> list[dict]:
    if not GEOCLIP_URL:
        raise ToolError("GeoCLIP is not configured")
    try:
        async with httpx.AsyncClient(timeout=GEOCLIP_TIMEOUT) as client:
            response = await client.post(f"{GEOCLIP_URL}/predict", params={"top_k": GEOCLIP_TOP_K},
                                         content=data, headers={"Content-Type": "application/octet-stream"})
    except httpx.HTTPError as exc:
        raise ToolError(f"GeoCLIP unreachable ({type(exc).__name__})") from exc
    if response.status_code != 200:
        raise ToolError(f"GeoCLIP returned HTTP {response.status_code}")
    return response.json().get("predictions") or []


def fuse(candidates: list[dict]) -> list[dict]:
    """Merge near-duplicates and reward agreement between independent sources."""
    merged: list[dict] = []
    for cand in sorted(candidates, key=lambda c: (c["radius_m"], -c["score"])):
        for m in merged:
            limit_km = max(m["radius_m"], cand["radius_m"]) / 1000 + 1
            if haversine_km(m["lat"], m["lon"], cand["lat"], cand["lon"]) <= limit_km:
                m["evidence"] += [e for e in cand["evidence"] if e not in m["evidence"]]
                for s in cand["sources"]:
                    if s not in m["sources"]:
                        m["sources"].append(s)
                m["score"] = max(m["score"], cand["score"])
                break
        else:
            merged.append({**cand, "sources": list(cand["sources"]), "evidence": list(cand["evidence"])})
    # agreement: other sources merged into this place, or pointing within
    # 50 km of it (or inside each other's radius), each add confidence
    for m in merged:
        agreeing = set(m["sources"][1:])
        for other in merged:
            if other is m:
                continue
            reach_km = max(50.0, m["radius_m"] / 1000, other["radius_m"] / 1000)
            if haversine_km(m["lat"], m["lon"], other["lat"], other["lon"]) <= reach_km:
                agreeing |= set(other["sources"])
        agreeing.discard(m["sources"][0])
        if agreeing:
            m["agrees_with"] = sorted(agreeing)
        m["score"] = round(min(1.0, m["score"] + 0.15 * len(agreeing)), 3)
        m["confidence"] = "high" if m["score"] >= 0.75 else "medium" if m["score"] >= 0.45 else "low"
        m["links"] = geo_links(m["lat"], m["lon"], None)
    merged.sort(key=lambda m: (-m["score"], m["radius_m"]))
    return merged


async def _label(fused: list[dict], top: int = 4) -> list[dict]:
    """Give the best candidates a human-readable place name (cached lookups)."""
    for cand in fused[:top]:
        if not cand.get("label"):
            place = await geocode.reverse(cand["lat"], cand["lon"], zoom=10)
            if place:
                cand["label"] = place["label"]
                cand["country_code"] = place["country_code"]
    return fused


async def analyze_upload(data: bytes) -> dict:
    """Step 1 on the server: EXIF, OCR, GeoCLIP; returns preview + candidates."""
    outcome_task = asyncio.to_thread(analyze_image, data, "")
    geoclip_task = _geoclip(data)
    outcome, geoclip = await asyncio.gather(outcome_task, geoclip_task, return_exceptions=True)
    if isinstance(outcome, BaseException):
        raise ToolError(f"Could not analyze the image: {outcome}")
    warnings = list(outcome.get("warnings") or [])
    results = [r for r in outcome["results"] if not r.get("platform", "").startswith("Reverse image")]
    candidates: list[dict] = []

    gps = next((r for r in results if r.get("platform") == "GPS location"), None)
    if gps:
        m = re.search(r"Decimal: (-?[\d.]+), (-?[\d.]+)", gps.get("info", ""))
        if m:
            candidates.append(_candidate(float(m.group(1)), float(m.group(2)), KIND_RADIUS["exif"],
                                         "EXIF GPS", 1.0, ["the camera recorded GPS coordinates"]))

    ocr = next((r.get("info", "") for r in results if r.get("platform") == "OCR text"), "")
    hints = text_hints(ocr)

    if isinstance(geoclip, BaseException):
        warnings.append(f"GeoCLIP: {geoclip}")
        geoclip = []
    total = sum(p["prob"] for p in geoclip) or 1.0
    for rank, pred in enumerate(geoclip):
        share = pred["prob"] / total
        candidates.append(_candidate(
            pred["lat"], pred["lon"], 50000, "GeoCLIP", 0.25 + 0.35 * share,
            [f"visual model guess #{rank + 1} ({share:.0%} of its top-{len(geoclip)} weight)"]))

    fused = await _label(fuse(candidates))
    step1 = {"ocr_text": ocr, "text_hints": hints, "raw_candidates": candidates,
             "preview_b64": outcome.get("preview", "")}
    vision = await server_vision(step1)
    clues = []
    if vision:
        fused = vision["candidates"]
        clues = vision["clues"]
        warnings.extend(vision["warnings"])
    return {
        "status": "success",
        "category": "geolocate",
        "vision": "server" if vision else "none",
        "clues": clues,
        "results": results,
        "ocr_text": ocr,
        "text_hints": hints,
        "candidates": fused,
        "raw_candidates": candidates,
        "preview_b64": outcome.get("preview", ""),
        "warnings": warnings,
        "notice": NOTICE,
    }


VISION_KINDS = ["business", "landmark", "street", "district", "city", "region", "country"]
VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "clues": {"type": "array", "items": {"type": "object", "properties": {
            "clue": {"type": "string"}, "points_to": {"type": "string"}}, "required": ["clue", "points_to"]}},
        "places": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "kind": {"type": "string", "enum": VISION_KINDS},
            "city": {"type": "string"}, "country": {"type": "string"},
            "confidence": {"type": "number"}, "evidence": {"type": "string"}},
            "required": ["name", "kind", "confidence", "evidence"]}},
        "country_codes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["clues", "places", "country_codes"],
}


def vision_prompt(ocr_text: str, hints: list[dict]) -> str:
    hint_text = "; ".join(f"{h['country']} ({h['evidence']})" for h in hints)
    return (
        "You are a photo geolocation analyst. Use ONLY what is visible: text on signs and "
        "shops, language and script, architecture, road markings and signs, licence-plate "
        "format, vehicles, vegetation, terrain, landmarks. Do not identify any person.\n"
        f'OCR text read from the photo: "{(ocr_text or "")[:500]}"\n'
        + (f"Text hints: {hint_text}\n" if hint_text else "")
        + "Return: clues (each visible clue and what it points to); places (at most 5, the most "
        "specific first: a business or landmark name you can actually read, then street, district, "
        "city, region, country) with the exact visible evidence and a confidence 0-1; "
        "country_codes (ISO 3166-1 alpha-2) of likely countries. If unsure, give a broader kind "
        "with low confidence instead of guessing a specific place."
    )


async def server_vision(step1: dict) -> dict | None:
    """Run the vision step on the server when the local model is reachable."""
    from services import ai
    if not step1.get("preview_b64") or not await ai.available():
        return None
    try:
        vision = await ai.chat_json(vision_prompt(step1.get("ocr_text", ""), step1.get("text_hints", [])),
                                    VISION_SCHEMA, model=ai.VISION_MODEL, images=[step1["preview_b64"]])
    except ai.AIUnavailable:
        return None
    codes = [c.upper() for c in vision.get("country_codes") or [] if isinstance(c, str) and len(c) == 2]
    codes += [h["country"] for h in step1.get("text_hints", []) if len(h["country"]) == 2]
    refined = await refine(step1.get("raw_candidates", []), vision.get("places") or [],
                           list(dict.fromkeys(codes))[:3])
    return {"candidates": refined["candidates"], "clues": (vision.get("clues") or [])[:10],
            "places": (vision.get("places") or [])[:6], "warnings": refined["warnings"]}


async def refine(raw_candidates: list[dict], places: list[dict], country_codes: list[str] | None = None) -> dict:
    """Step 2: geocode the place names a vision model saw, then fuse everything."""
    candidates = [c for c in raw_candidates if isinstance(c, dict) and "lat" in c][:20]
    codes = [c.upper() for c in (country_codes or []) if isinstance(c, str) and len(c) == 2][:3]
    notes = []
    for place in [p for p in places if isinstance(p, dict)][:MAX_VISION_PLACES]:
        name = str(place.get("name") or "").strip()
        kind = str(place.get("kind") or "city").lower()
        if kind not in KIND_WEIGHT:
            kind = "city"
        if not name:
            continue
        query = ", ".join(x for x in [name, str(place.get("city") or ""), str(place.get("country") or "")] if x)
        hits = await geocode.search(query, codes or None, limit=1)
        if not hits and codes:
            hits = await geocode.search(query, None, limit=1)
        if not hits:
            notes.append(f"'{query}' was not found on OpenStreetMap")
            continue
        hit = hits[0]
        confidence = max(0.1, min(1.0, float(place.get("confidence") or 0.5)))
        why = str(place.get("evidence") or place.get("why") or "").strip()[:200]
        candidates.append(_candidate(
            hit["lat"], hit["lon"], KIND_RADIUS[kind], "Vision + OpenStreetMap",
            KIND_WEIGHT[kind] * confidence,
            [f"vision model saw {kind} '{name}'" + (f": {why}" if why else "")],
            label=hit["label"]))
    fused = await _label(fuse(candidates))
    return {"status": "success", "category": "geolocate", "candidates": fused,
            "warnings": notes, "notice": NOTICE}
