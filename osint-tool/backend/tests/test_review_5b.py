"""Faza 5b: regressions for the second review's findings."""
import time

import pytest

from tools import holehe_runner as hr
from tools import sanctions_index as si
from tools import uz_registry as uz
from tools.base import IndexNotReady


# ---- B1: a long "name" must not explode into millions of subsets ----

def test_long_query_is_bounded(tmp_path):
    db = str(tmp_path / "s.db")
    si.store_source("uk", si.parse_uk(b"Unique ID,Name 6,Name 1,Name type,Designation Type\n"
                                      b"X1,PUTIN,Vladimir,Primary Name,Individual\n"), "a", "u", db)
    name = " ".join(f"{a}{b}" for a in "bdfgklmnprst" for b in "aeiou")   # 60 distinct tokens
    started = time.monotonic()
    assert si.search(name, path=db) == []
    assert time.monotonic() - started < 2.0


# ---- B2: missing indexes are errors, never "no match" ----

def test_sanctions_search_without_index_raises(tmp_path):
    with pytest.raises(IndexNotReady):
        si.search("Vladimir Putin", path=str(tmp_path / "missing.db"))


def test_uz_register_search_without_index_raises(tmp_path):
    with pytest.raises(IndexNotReady):
        uz.search_org("Hamkorbank", path=str(tmp_path / "missing.db"))
    with pytest.raises(IndexNotReady):
        uz.search_person("Behzod Normatov", path=str(tmp_path / "missing.db"))


@pytest.mark.asyncio
async def test_company_search_warns_when_registers_missing(monkeypatch):
    from services import investigate as inv

    async def gleif(_q):
        return {"results": [{"platform": "Company (GLEIF)", "status": "found"}], "pivots": []}

    async def no_disclosure(_q):
        return {"results": [], "pivots": []}

    def not_ready(_q):
        raise IndexNotReady("Uzbek register index is not built yet")
    monkeypatch.setattr(inv, "run_company_search", gleif)
    monkeypatch.setattr(inv.openinfo, "lookup", no_disclosure)
    monkeypatch.setattr(inv.uz_registry, "search_org", not_ready)
    out = await inv._investigate_company("Acme")
    assert any("not built yet" in w for w in out["warnings"])


# ---- B3: Holehe policy fails closed ----

def _mod(method, category="social_media"):
    async def func(email, client, out):
        return None
    return hr.HoleheModule("x", category, method, func)


@pytest.mark.parametrize("method", ["unknown", "password_recovery", "forgot", "", "recovery"])
def test_unknown_methods_never_run(method, monkeypatch):
    monkeypatch.setenv("HOLEHE_ALLOW_LOGIN", "1")
    assert not hr.policy_allows(_mod(method))


def test_known_methods(monkeypatch):
    monkeypatch.delenv("HOLEHE_ALLOW_LOGIN", raising=False)
    assert hr.policy_allows(_mod("register")) and hr.policy_allows(_mod("other"))
    assert not hr.policy_allows(_mod("login"))
    monkeypatch.setenv("HOLEHE_ALLOW_LOGIN", "1")
    assert hr.policy_allows(_mod("login"))


# ---- M6: PEPs are stored per country ----

def test_pep_sources_are_per_country(tmp_path):
    db = str(tmp_path / "s.db")
    pep = si.parse_peps({"results": {"bindings": [{"p": {"value": "http://www.wikidata.org/entity/Q1"},
                                                    "names": {"value": "Shavkat Mirziyoyev"}}]}}, "UZ")
    si.store_source("pep:UZ", pep, "a", "u", db)
    si.store_source("pep:KZ", [], "b", "u", db)          # a failed/empty country does not wipe UZ
    assert si.has_peps(db)
    hits = si.search("Shavkat Mirziyoyev", path=db)
    assert hits and si.to_result(hits[0])["platform"] == "PEP (Wikidata)"


# ---- M1: bounded bodies in and out ----

@pytest.mark.asyncio
async def test_oversized_request_is_refused_before_reading():
    from httpx import ASGITransport, AsyncClient

    import main
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/geolocate", content=b"x",
                                 headers={"content-length": str(main.MAX_REQUEST_BYTES + 1),
                                          "content-type": "multipart/form-data; boundary=x"})
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_safe_get_stops_reading_at_the_limit(monkeypatch):
    import httpx

    from tools import net_guard

    async def fake_check(url):
        from urllib.parse import urlparse
        return urlparse(url), "example.com", ["93.184.216.34"]
    monkeypatch.setattr(net_guard, "_check_url", fake_check)

    def handler(request):
        return httpx.Response(200, content=b"a" * 5000)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ok = await net_guard.safe_get(client, "http://example.com/x", max_bytes=10_000)
        assert len(ok.content) == 5000
        with pytest.raises(net_guard.ResponseTooLarge):
            await net_guard.safe_get(client, "http://example.com/x", max_bytes=1000)


# ---- M3: geocoding failures and client-supplied candidates ----

@pytest.mark.asyncio
async def test_geocode_network_error_is_none(monkeypatch):
    import httpx

    from tools import geocode

    async def no_cache(_k):
        return None

    async def boom(self, *a, **k):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(geocode, "get_cached_json", no_cache)
    monkeypatch.setattr(geocode, "_last_call", 0.0)
    monkeypatch.setattr(httpx.AsyncClient, "get", boom)
    assert await geocode.reverse(41.3, 69.2) is None
    assert await geocode.search("Tashkent") == []


@pytest.mark.asyncio
async def test_refine_rebuilds_client_candidates(monkeypatch):
    from services import geolocate as geo

    async def no_reverse(*a, **k):
        return None
    monkeypatch.setattr(geo.geocode, "reverse", no_reverse)
    out = await geo.refine([{"lat": 41.3, "lon": 69.2}, {"lat": "x"}, {"lat": 999, "lon": 0}, "junk",
                            {"lat": 40.0, "lon": 70.0, "radius_m": -5, "score": 7, "sources": ["GeoCLIP"]}], [])
    assert len(out["candidates"]) == 2
    assert all(30 <= c["radius_m"] <= 1_000_000 and 0 <= c["score"] <= 1 for c in out["candidates"])


# ---- M4: a namesake beyond the fetched entities blocks "unique" ----

def test_grading_considers_namesakes_not_fetched_in_full():
    from tools import entity_intel as ei
    detail = ({"platform": "Wikidata", "title": "Jane Roe"}, [{"type": "username", "value": "jroe"}], True)
    assert ei._grade_pivots("Jane Roe", [detail])[0]["via"] == "knowledge_base"
    assert ei._grade_pivots("Jane Roe", [detail], other_matching_humans=1)[0]["via"] == "name_match"


# ---- M5: decompression bombs are refused ----

def test_huge_pixel_count_is_refused():
    import io

    from PIL import Image

    from tools import image_intel
    buf = io.BytesIO()
    Image.new("1", (8000, 6000)).save(buf, format="PNG")          # 48 MP, tiny file
    out = image_intel.analyze_image(buf.getvalue(), "")
    assert any("Could not decode image" in w for w in out["warnings"])


# ---- L: robots.txt server error means "do not crawl" ----

@pytest.mark.asyncio
async def test_robots_server_error_stops_crawl(monkeypatch):
    import httpx

    from tools import site_contacts as sc
    requested = []

    async def fake_safe_get(client, url):
        requested.append(url)
        return httpx.Response(503, text="down", request=httpx.Request("GET", url))
    monkeypatch.setattr(sc, "safe_get", fake_safe_get)
    found, notes = await sc.crawl_contacts("acme.uz")
    assert found == [] and len(requested) == 1 and "not crawling" in notes[0]
