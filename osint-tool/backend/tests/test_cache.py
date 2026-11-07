import cache
from services import investigate


async def test_memory_cache_roundtrip(monkeypatch):
    monkeypatch.setattr(cache, "REDIS_URL", "")
    cache.clear_memory_cache()

    await cache.set_cached_json("osint:test", {"status": "success"}, 60)

    assert await cache.get_cached_json("osint:test") == {"status": "success"}


async def test_memory_cache_expiry(monkeypatch):
    monkeypatch.setattr(cache, "REDIS_URL", "")
    cache.clear_memory_cache()

    await cache.set_cached_json("osint:test", {"status": "success"}, -1)

    assert await cache.get_cached_json("osint:test") is None


async def test_memory_cache_missing_key(monkeypatch):
    monkeypatch.setattr(cache, "REDIS_URL", "")
    cache.clear_memory_cache()

    assert await cache.get_cached_json("osint:missing") is None


async def test_investigation_result_is_cached(monkeypatch):
    monkeypatch.setattr(cache, "REDIS_URL", "")
    cache.clear_memory_cache()
    calls = {"count": 0}

    async def fake_run_name_search(name: str) -> dict:
        calls["count"] += 1
        return {
            "results": [
                {
                    "platform": "Example",
                    "url": "https://example.com/john",
                    "status": "found",
                }
            ],
            "dropped": 0,
        }

    async def fake_run_name_sources(name: str) -> dict:
        return {"results": [], "warnings": [], "pivots": []}

    monkeypatch.setattr(investigate, "run_name_search", fake_run_name_search)
    monkeypatch.setattr(investigate, "run_name_sources", fake_run_name_sources)

    first = await investigate.investigate_name("John Doe")
    second = await investigate.investigate_name("john doe")

    assert first["count"] == 1
    assert calls["count"] == 1
    assert second.get("cached") is True
