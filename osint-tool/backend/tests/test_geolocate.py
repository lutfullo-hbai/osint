"""Image geolocation: hints, fusion, the two server steps, upload endpoint."""
import io

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

import main
from services import geolocate as geo


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 160, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def test_text_hints_from_phone_and_domain():
    hints = geo.text_hints("Tel: +998 (90) 123-45-67 www.mysite.uz")
    assert {"country": "UZ", "evidence": "phone number with +998"} in hints
    assert any(h["evidence"] == "web address ending in .uz" for h in hints)
    assert geo.text_hints("no clues here") == []


def test_fuse_merges_nearby_and_rewards_agreement():
    tashkent_geoclip = geo._candidate(41.30, 69.24, 50000, "GeoCLIP", 0.4, ["visual guess"])
    tashkent_vision = geo._candidate(41.311, 69.279, 15000, "Vision + OpenStreetMap", 0.5,
                                     ["vision model saw city 'Tashkent'"])
    paris = geo._candidate(48.85, 2.35, 50000, "GeoCLIP", 0.3, ["visual guess"])
    out = geo.fuse([tashkent_geoclip, tashkent_vision, paris])
    best = out[0]
    assert set(best["sources"]) == {"GeoCLIP", "Vision + OpenStreetMap"}
    assert best["score"] > 0.5 and len(best["evidence"]) == 2
    assert out[-1]["lat"] == 48.85 and out[-1]["confidence"] == "low"
    assert "Google Maps" in best["links"]


def test_exif_gps_wins():
    exif = geo._candidate(40.99, 71.67, 30, "EXIF GPS", 1.0, ["camera GPS"])
    other = geo._candidate(48.85, 2.35, 50000, "GeoCLIP", 0.5, ["guess"])
    out = geo.fuse([other, exif])
    assert out[0]["sources"] == ["EXIF GPS"] and out[0]["confidence"] == "high"


@pytest.mark.asyncio
async def test_analyze_upload_without_geoclip_still_works(monkeypatch):
    monkeypatch.setattr(geo, "GEOCLIP_URL", "")

    async def no_reverse(*a, **k):
        return None
    monkeypatch.setattr(geo.geocode, "reverse", no_reverse)
    out = await geo.analyze_upload(_jpeg())
    assert out["status"] == "success" and out["candidates"] == []
    assert out["preview_b64"] and any("GeoCLIP" in w for w in out["warnings"])
    assert "not people" in out["notice"]


@pytest.mark.asyncio
async def test_analyze_upload_uses_geoclip_predictions(monkeypatch):
    async def fake_geoclip(_data):
        return [{"lat": 41.31, "lon": 69.28, "prob": 0.6}, {"lat": 40.99, "lon": 71.67, "prob": 0.4}]

    async def fake_reverse(lat, lon, zoom=10):
        return {"label": f"place {lat}", "country": "Uzbekistan", "country_code": "UZ", "city": "x"}
    monkeypatch.setattr(geo, "_geoclip", fake_geoclip)
    monkeypatch.setattr(geo.geocode, "reverse", fake_reverse)
    out = await geo.analyze_upload(_jpeg())
    assert len(out["candidates"]) == 2 and out["candidates"][0]["sources"] == ["GeoCLIP"]
    assert out["candidates"][0]["label"].startswith("place") and len(out["raw_candidates"]) == 2


@pytest.mark.asyncio
async def test_refine_geocodes_vision_places(monkeypatch):
    calls = []

    async def fake_search(query, codes=None, limit=3):
        calls.append((query, codes))
        if "Chorsu" in query:
            return [{"lat": 41.326, "lon": 69.235, "label": "Chorsu Bazaar, Tashkent", "kind": "x",
                     "importance": 0.6, "bbox": []}]
        return []

    async def fake_reverse(*a, **k):
        return None
    monkeypatch.setattr(geo.geocode, "search", fake_search)
    monkeypatch.setattr(geo.geocode, "reverse", fake_reverse)
    prior = [geo._candidate(41.30, 69.24, 50000, "GeoCLIP", 0.4, ["visual guess"])]
    out = await geo.refine(prior, [
        {"name": "Chorsu Bazaar", "kind": "landmark", "city": "Tashkent", "confidence": 0.8,
         "evidence": "blue dome and sign 'Chorsu'"},
        {"name": "Nowhere Plaza", "kind": "business", "confidence": 0.5},
    ], ["uz"])
    best = out["candidates"][0]
    assert best["label"] == "Chorsu Bazaar, Tashkent" and best["radius_m"] == 300
    assert "GeoCLIP" in best.get("agrees_with", [])
    assert calls[0] == ("Chorsu Bazaar, Tashkent", ["UZ"])
    assert any("Nowhere Plaza" in w for w in out["warnings"])


@pytest.mark.asyncio
async def test_upload_endpoint(monkeypatch):
    async def fake_analyze(data):
        assert data[:2] == b"\xff\xd8"        # the uploaded JPEG bytes arrive intact
        return {"status": "success", "candidates": []}
    monkeypatch.setattr(geo, "analyze_upload", fake_analyze)
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.post("/api/geolocate", files={"file": ("p.jpg", _jpeg(), "image/jpeg")})
        empty = await client.post("/api/geolocate", data={})
    assert ok.status_code == 200 and ok.json()["status"] == "success"
    assert empty.status_code == 400
