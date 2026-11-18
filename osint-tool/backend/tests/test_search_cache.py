"""3b.2: SearXNG results cached for a day; per-engine health recorded."""
import httpx
import pytest

import cache
from routers import sources as sources_router
from tools import public_search as ps


@pytest.fixture(autouse=True)
def memory_cache(monkeypatch):
    monkeypatch.setattr(cache, "_memory", {})
    monkeypatch.setattr(ps, "_engine_stats_memory", {})

    async def no_client():
        return None
    monkeypatch.setattr(cache, "get_client", no_client)
    monkeypatch.setenv("SEARXNG_URL", "http://searxng:8080")
    monkeypatch.setattr(ps, "SEARXNG_DELAY_SECONDS", 0)


def _patch_transport(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)
    monkeypatch.setattr(ps.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_identical_query_is_served_from_cache(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={
            "results": [{"url": "https://github.com/jane", "title": "jane", "engines": ["brave"]}],
            "unresponsive_engines": [["google", "access denied"]]})
    _patch_transport(monkeypatch, handler)
    first = await ps._searxng_search(['"jane"'], 10)
    second = await ps._searxng_search(['"jane"'], 10)
    assert first == second and len(first) == 1 and calls["n"] == 1


@pytest.mark.asyncio
async def test_empty_answer_while_engines_blocked_is_not_cached(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"results": [],
                                         "unresponsive_engines": [["brave", "too many requests"]]})
    _patch_transport(monkeypatch, handler)
    await ps._searxng_search(["q"], 10)
    await ps._searxng_search(["q"], 10)
    assert calls["n"] == 2          # asked again: the first empty answer was not a real answer


@pytest.mark.asyncio
async def test_engine_health_is_recorded_and_summarised(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={
            "results": [{"url": "https://x.com/a", "title": "a", "engines": ["brave", "bing"]}],
            "unresponsive_engines": [["google", "access denied"], ["duckduckgo", "CAPTCHA"]]})
    _patch_transport(monkeypatch, handler)
    await ps._searxng_search(["q1"], 10)
    await ps._searxng_search(["q2"], 10)
    stats = await ps.engine_stats()
    assert stats["brave"]["ok"] == 2 and stats["google"]["fail"] == 2
    assert stats["duckduckgo"]["last_error"] == "CAPTCHA"
    summary = await sources_router._engine_summary()
    assert "brave 100% ok" in summary and "google failing (access denied)" in summary
