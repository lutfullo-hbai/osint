"""10.5f: DEV Community refuses parallel calls (429, Retry-After: 1). Calls are
spaced out, one short 429 is retried, and answers are cached."""
import asyncio

import httpx
import pytest

from tools import public_profiles as pp
from tools.base import ToolError

USER = {"username": "ben", "name": "Ben Halpern", "summary": "", "location": "NYC", "website_url": ""}


@pytest.fixture()
def clock(monkeypatch):
    """A fake clock: _sleep advances it instead of waiting."""
    now = [1000.0]
    waits = []

    async def fake_sleep(seconds):
        waits.append(round(seconds, 3))
        now[0] += seconds

    monkeypatch.setattr(pp.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(pp, "_sleep", fake_sleep)
    return waits


def client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_parallel_calls_are_spaced_out(clock):
    sent = []

    def handler(request):
        sent.append(pp.time.monotonic())
        return httpx.Response(404)

    async with client_for(handler) as client:
        await asyncio.gather(*(pp.devto_profile(client, f"user{i}") for i in range(4)))
    assert len(sent) == 4
    assert all(b - a >= 1.0 for a, b in zip(sent, sent[1:]))   # one call a second, never a burst
    assert sent[0] == 1000.0                                     # the first one does not wait


@pytest.mark.asyncio
async def test_other_apis_are_not_paced(clock):
    async with client_for(lambda r: httpx.Response(404)) as client:
        await asyncio.gather(*(pp.fetch_json(client, f"https://api.github.com/users/u{i}") for i in range(3)))
    assert clock == []


@pytest.mark.asyncio
async def test_short_429_is_retried_once(clock):
    answers = [httpx.Response(429, headers={"retry-after": "1"}), httpx.Response(200, json=USER)]
    calls = []

    def handler(request):
        calls.append(request)
        return answers.pop(0)

    async with client_for(handler) as client:
        entry = await pp.devto_profile(client, "ben")
    assert entry["url"] == "https://dev.to/ben" and "Ben Halpern" in entry["info"]
    assert len(calls) == 2 and clock == [1.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_after", [None, "60", "Wed, 21 Nov 2026 10:00:00 GMT", "-1"])
async def test_429_without_short_retry_after_fails_without_retry(clock, retry_after):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": retry_after} if retry_after else {})

    async with client_for(handler) as client:
        with pytest.raises(ToolError, match="rate limit"):
            await pp.devto_profile(client, "ben")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_second_429_is_reported_not_retried_again(clock):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "1"})

    async with client_for(handler) as client:
        with pytest.raises(ToolError, match="rate limit"):
            await pp.devto_profile(client, "ben")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_a_429_pushes_back_the_whole_queue(clock):
    answers = {"a": [httpx.Response(429, headers={"retry-after": "3"}), httpx.Response(404)], "b": [httpx.Response(404)]}

    def handler(request):
        return answers[request.url.params["url"]].pop(0)

    async with client_for(handler) as client:
        await pp.devto_profile(client, "a")
        await pp.devto_profile(client, "b")
    # a: refused, waits out Retry-After (3 s); b then waits its own 1 s slot after a's retry
    assert clock == [3.0, 1.0]


@pytest.mark.asyncio
async def test_a_long_queue_fails_fast(monkeypatch):
    """Five calls arrive at the same moment; with a 2 s limit the 4th and 5th
    (3 s and 4 s away) fail at once instead of stalling the scan."""
    waits = []

    async def sleep_without_time_passing(seconds):
        waits.append(seconds)

    monkeypatch.setattr(pp.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(pp, "_sleep", sleep_without_time_passing)
    monkeypatch.setattr(pp, "PACE_MAX_WAIT", 2.0)
    async with client_for(lambda r: httpx.Response(404)) as client:
        results = await asyncio.gather(*(pp.devto_profile(client, f"u{i}") for i in range(5)),
                                       return_exceptions=True)
    assert [type(r).__name__ for r in results] == ["NoneType", "NoneType", "NoneType", "ToolError", "ToolError"]
    assert waits == [1.0, 2.0]


@pytest.mark.asyncio
async def test_devto_answers_are_cached(clock):
    calls = []

    def handler(request):
        calls.append(request.url.params["url"])
        return httpx.Response(200, json=USER) if request.url.params["url"] == "ben" else httpx.Response(404)

    async with client_for(handler) as client:
        for _ in range(3):
            assert await pp.devto_profile(client, "ben")
            assert await pp.devto_profile(client, "nobody") is None
    assert calls == ["ben", "nobody"]


@pytest.mark.asyncio
async def test_username_is_url_encoded(clock):
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(404)

    async with client_for(handler) as client:
        await pp.devto_profile(client, "a&b=c")
    assert seen[0].params["url"] == "a&b=c" and "b" not in seen[0].params


def test_paced_failures_show_as_unchecked():
    from services.deep_scan import unchecked_sources
    warnings = ["DEV Community: rate limit: too many queued requests, try again later.",
                "DEV Community: rate limit reached."]
    assert unchecked_sources({"warnings": warnings}) == ["DEV Community"]
