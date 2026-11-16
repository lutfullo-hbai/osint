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

    async def empty_results(name: str) -> dict:
        return {"results": [], "pivots": []}

    async def empty_sanctions(name: str) -> dict:
        return {"results": [], "warnings": []}

    monkeypatch.setattr(investigate, "run_person_entity", empty_results)
    monkeypatch.setattr(investigate, "run_sanctions_check", empty_sanctions)

    first = await investigate.investigate_name("John Doe")
    second = await investigate.investigate_name("john doe")

    assert first["count"] == 1
    assert calls["count"] == 1
    assert second.get("cached") is True


async def test_investigate_fresh_skips_cache_read_but_refreshes_it(monkeypatch):
    from services import investigate as inv

    monkeypatch.setattr(cache, "REDIS_URL", "")
    cache.clear_memory_cache()
    calls = []

    async def producer(q):
        calls.append(q)
        return {"status": "success", "n": len(calls)}

    async def handler(query):
        return await inv._cached("osint:t:fresh", producer, query)

    monkeypatch.setitem(inv.HANDLERS, "username", handler)

    first = await inv.investigate("username", "x")
    cached = await inv.investigate("username", "x")
    assert cached["n"] == 1 and cached.get("cached") is True  # served from cache

    fresh = await inv.investigate("username", "x", fresh=True)
    assert fresh["n"] == 2 and not fresh.get("cached")  # upstream called again
    assert len(calls) == 2
    # the fresh result replaced the cached one, and the flag does not leak
    again = await inv.investigate("username", "x")
    assert again["n"] == 2 and again.get("cached") is True
    assert first["n"] == 1
