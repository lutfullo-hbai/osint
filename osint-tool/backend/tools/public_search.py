import asyncio
import os
import re
import time

from urllib.parse import urlparse

import httpx

from tools.base import ToolError
from tools.net_guard import UnsafeURLError, safe_get

SEARCH_TIMEOUT_SECONDS = 150
DEFAULT_MAX_RESULTS = 15
DELAY_BETWEEN_BATCHES_SECONDS = 2.5
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
BRAVE_DELAY_SECONDS = 1.1
SEARXNG_TIMEOUT_SECONDS = 20
SEARXNG_DELAY_SECONDS = 0.3

VERIFY_TIMEOUT_SECONDS = 12
MAX_CONCURRENT_FETCHES = 6
FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

PLATFORM_LABELS = {
    "linkedin.com": "LinkedIn",
    "x.com": "X (Twitter)",
    "twitter.com": "X (Twitter)",
    "instagram.com": "Instagram",
    "github.com": "GitHub",
    "tiktok.com": "TikTok",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "medium.com": "Medium",
    "dev.to": "DEV Community",
    "t.me": "Telegram",
    "reddit.com": "Reddit",
    "facebook.com": "Facebook",
    "fb.com": "Facebook",
    "pinterest.com": "Pinterest",
    "threads.net": "Threads",
    "vk.com": "VK",
    "ok.ru": "Odnoklassniki",
    "substack.com": "Substack",
    "olx.uz": "OLX Uzbekistan",
    "torg.uz": "Torg.uz",
    "avito.ru": "Avito",
    "olx.ru": "OLX",
    "myshop.uz": "Myshop.uz",
    "asaxiy.uz": "Asaxiy",
    "kun.uz": "Kun.uz",
    "daryo.uz": "Daryo.uz",
    "gov.uz": "Gov.uz",
    "wikipedia.org": "Wikipedia",
    "gazeta.uz": "Gazeta.uz",
    "uza.uz": "UzA",
    "qalampir.uz": "Qalampir.uz",
    "hh.uz": "hh.uz",
    "hh.ru": "hh.ru",
    "researchgate.net": "ResearchGate",
    "academia.edu": "Academia.edu",
    "habr.com": "Habr",
    "twitch.tv": "Twitch",
    "soundcloud.com": "SoundCloud",
    "spotify.com": "Spotify",
    "steamcommunity.com": "Steam",
}


def platform_from_url(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower().removeprefix("www.")
    except ValueError:
        return "Web"
    if netloc in PLATFORM_LABELS:
        return PLATFORM_LABELS[netloc]
    parts = netloc.split(".")
    root = ".".join(parts[-2:]) if len(parts) >= 2 else netloc
    return PLATFORM_LABELS.get(root, root.replace(".", " ").title() or "Web")


def _search_sync(
    query_batches: list[str], max_results_per_batch: int = DEFAULT_MAX_RESULTS
) -> list[dict]:
    from ddgs import DDGS

    results = []
    seen = set()
    failed_batches = 0

    with DDGS() as client:
        for index, batch in enumerate(query_batches):
            if index > 0:
                time.sleep(DELAY_BETWEEN_BATCHES_SECONDS)
            try:
                items = client.text(
                    batch,
                    max_results=max_results_per_batch,
                    region="wt-wt",
                    safesearch="moderate",
                )
            except Exception:
                failed_batches += 1
                continue

            for item in items or []:
                url = (item.get("href") or "").strip()
                if not url.startswith("http"):
                    continue
                key = url.split("#")[0].lower().rstrip("/")
                if key in seen:
                    continue
                seen.add(key)
                results.append(
                    {
                        "platform": platform_from_url(url),
                        "source": "web_search",
                        "url": url,
                        "title": (item.get("title") or "").strip(),
                        "info": (item.get("body") or "").strip()[:300],
                        "status": "found",
                    }
                )

    if not results and failed_batches == len(query_batches):
        raise ToolError(
            "Search engine did not respond. It may be rate-limiting this IP - "
            "try again in a minute."
        )
    return results


async def _brave_search(
    query_batches: list[str], max_results_per_batch: int
) -> list[dict]:
    """Brave Search API — richer, Google-grade results. Used when a key is set."""
    api_key = os.environ.get("BRAVE_API_KEY", "").strip()
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    results = []
    seen = set()
    failed = 0
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        for index, batch in enumerate(query_batches):
            if index > 0:
                await asyncio.sleep(BRAVE_DELAY_SECONDS)
            try:
                response = await client.get(
                    BRAVE_ENDPOINT,
                    params={"q": batch, "count": max_results_per_batch},
                )
                if response.status_code == 401:
                    raise ToolError("Brave Search rejected the API key.")
                if response.status_code != 200:
                    failed += 1
                    continue
                web = (response.json().get("web") or {}).get("results") or []
            except ToolError:
                raise
            except Exception:
                failed += 1
                continue
            for item in web:
                url = (item.get("url") or "").strip()
                if not url.startswith("http"):
                    continue
                key = url.split("#")[0].lower().rstrip("/")
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "platform": platform_from_url(url),
                    "source": "web_search",
                    "url": url,
                    "title": (item.get("title") or "").strip(),
                    "info": (item.get("description") or "").strip()[:300],
                    "status": "found",
                })
    if not results and failed == len(query_batches):
        raise ToolError("Brave Search did not respond.")
    return results


def parse_searxng(data: dict, limit: int) -> list[dict]:
    """SearXNG JSON -> our result entries."""
    out = []
    for item in (data.get("results") or [])[:limit]:
        url = (item.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        out.append({
            "platform": platform_from_url(url),
            "source": "web_search",
            "url": url,
            "title": (item.get("title") or "").strip(),
            "info": (item.get("content") or "").strip()[:300],
            "status": "found",
            "engines": item.get("engines") or ([item["engine"]] if item.get("engine") else []),
        })
    return out


# Search results barely change within a day; caching them spares the engines
# (and our IP) repeated identical queries. Empty answers are kept shorter.
SEARCH_CACHE_TTL = 24 * 3600
EMPTY_CACHE_TTL = 3600
PARTIAL_CACHE_TTL = 2 * 3600
ENGINE_STATS_KEY = "osint:searxng:engines"
_engine_stats_memory: dict[str, dict] = {}


def _batch_key(batch: str, limit: int) -> str:
    import hashlib
    return "osint:search:" + hashlib.sha256(f"{limit}|{batch}".encode()).hexdigest()


async def record_engine_stats(data: dict) -> None:
    """Per-engine success/failure counts from one SearXNG answer."""
    import json as _json
    import time as _time

    from cache import get_client

    contributed = {e for item in data.get("results") or [] for e in (item.get("engines") or [])}
    failed = {str(pair[0]): str(pair[1]) for pair in data.get("unresponsive_engines") or []
              if isinstance(pair, (list, tuple)) and len(pair) == 2}
    if not contributed and not failed:
        return
    client = await get_client()
    current = {}
    if client is not None:
        try:
            raw = await client.hgetall(ENGINE_STATS_KEY)
            current = {k: _json.loads(v) for k, v in (raw or {}).items()}
        except Exception:  # noqa: BLE001 - stats are advisory
            current = {}
    else:
        current = dict(_engine_stats_memory)
    now = _time.time()
    updates = {}
    for engine in contributed | set(failed):
        row = dict(current.get(engine) or {"ok": 0, "fail": 0})
        if engine in failed:
            row["fail"] = row.get("fail", 0) + 1
            row["last_error"] = failed[engine][:80]
        else:
            row["ok"] = row.get("ok", 0) + 1
        row["last_seen"] = now
        updates[engine] = row
    if client is not None:
        try:
            await client.hset(ENGINE_STATS_KEY, mapping={k: _json.dumps(v) for k, v in updates.items()})
        except Exception:  # noqa: BLE001
            pass
    else:
        _engine_stats_memory.update(updates)


async def engine_stats() -> dict[str, dict]:
    import json as _json

    from cache import get_client
    client = await get_client()
    if client is None:
        return dict(_engine_stats_memory)
    try:
        raw = await client.hgetall(ENGINE_STATS_KEY)
        return {k: _json.loads(v) for k, v in (raw or {}).items()}
    except Exception:  # noqa: BLE001
        return {}


async def _searxng_search(query_batches: list[str], max_results_per_batch: int) -> list[dict]:
    """Our own SearXNG: one query fans out to Google, Bing, Brave, Startpage...

    The URL is operator configuration (the compose-internal service), so it is
    called directly rather than through the public-URL SSRF guard.
    """
    from cache import get_cached_json, set_cached_json

    base = os.environ.get("SEARXNG_URL", "").strip().rstrip("/")
    results, seen, failed = [], set(), 0
    sent = 0
    async with httpx.AsyncClient(timeout=SEARXNG_TIMEOUT_SECONDS) as client:
        for batch in query_batches:
            key = _batch_key(batch, max_results_per_batch)
            items = await get_cached_json(key)
            if items is None:
                if sent > 0:
                    await asyncio.sleep(SEARXNG_DELAY_SECONDS)
                sent += 1
                try:
                    response = await client.get(
                        f"{base}/search",
                        params={"q": batch, "format": "json", "safesearch": 0},
                    )
                    if response.status_code != 200:
                        failed += 1
                        continue
                    data = response.json()
                    items = parse_searxng(data, max_results_per_batch)
                except (httpx.HTTPError, ValueError):
                    failed += 1
                    continue
                await record_engine_stats(data)
                engines_failed = bool(data.get("unresponsive_engines"))
                if items:
                    # some engines down: their results may be missing, keep it short
                    await set_cached_json(key, items, PARTIAL_CACHE_TTL if engines_failed else SEARCH_CACHE_TTL)
                elif not engines_failed:
                    # a real "nothing found"; an empty answer while engines are
                    # blocked is not cached at all
                    await set_cached_json(key, items, EMPTY_CACHE_TTL)
            for item in items:
                url_key = item["url"].split("#")[0].lower().rstrip("/")
                if url_key not in seen:
                    seen.add(url_key)
                    results.append(item)
    if not results and failed == len(query_batches):
        raise ToolError("SearXNG did not respond.")
    return results


def _providers(max_results_per_batch: int) -> list[tuple[str, object]]:
    """Search backends in order of preference; each later one is a fallback."""
    providers = []
    if os.environ.get("BRAVE_API_KEY", "").strip():
        providers.append(("Brave Search", lambda b: _brave_search(b, max_results_per_batch)))
    if os.environ.get("SEARXNG_URL", "").strip():
        providers.append(("SearXNG", lambda b: _searxng_search(b, max_results_per_batch)))
    providers.append(("DuckDuckGo", lambda b: asyncio.to_thread(_search_sync, b, max_results_per_batch)))
    return providers


async def search_public(
    query_batches: list[str],
    timeout: int = SEARCH_TIMEOUT_SECONDS,
    max_results_per_batch: int = DEFAULT_MAX_RESULTS,
) -> list[dict]:
    """Run the batches on the first search backend that answers.

    A backend that fails or returns nothing hands over to the next one, so a
    single engine rate-limiting this IP no longer empties every name search.
    """
    batches = list(query_batches)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    errors = []
    for label, run in _providers(max_results_per_batch):
        remaining = deadline - loop.time()
        if remaining <= 1:
            break
        try:
            results = await asyncio.wait_for(run(batches), timeout=remaining)
        except asyncio.TimeoutError:
            errors.append(f"{label} timed out")
            continue
        except ImportError:
            errors.append(f"{label}: package not installed")
            continue
        except ToolError as exc:
            errors.append(f"{label}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - one backend must not sink search
            errors.append(f"{label} failed unexpectedly: {type(exc).__name__}")
            continue
        if results:
            return results
        errors.append(f"{label}: no results")
    if errors and all(not e.endswith("no results") for e in errors):
        raise ToolError(
            "Search engine did not respond (" + "; ".join(errors) + "). It may be "
            "rate-limiting this IP - try again in a minute."
        )
    return []


def _digit_pattern(digits: str) -> re.Pattern:
    separator = r"[\s\-.()]{0,3}"
    body = separator.join(re.escape(char) for char in digits)
    return re.compile(body)


async def filter_results_containing(
    results: list[dict], digit_strings: list[str]
) -> tuple[list[dict], int]:
    clean_digits = [re.sub(r"\D", "", candidate) for candidate in digit_strings]
    patterns = [
        _digit_pattern(digits) for digits in clean_digits if len(digits) >= 7
    ]
    if not patterns:
        return list(results), 0

    async def page_matches(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore) -> bool:
        if not url.startswith("http"):
            return False
        async with semaphore:
            try:
                response = await safe_get(client, url)
            except (httpx.HTTPError, UnsafeURLError):
                return False
        if response.status_code != 200:
            return False
        html = response.text
        return any(pattern.search(html) for pattern in patterns)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    kept = []
    dropped = 0
    async with httpx.AsyncClient(
        headers=FETCH_HEADERS,
        follow_redirects=False,
        timeout=httpx.Timeout(VERIFY_TIMEOUT_SECONDS),
    ) as client:
        checks = [page_matches(client, item.get("url", ""), semaphore) for item in results]
        outcomes = await asyncio.gather(*checks, return_exceptions=True)

    for item, outcome in zip(results, outcomes):
        if outcome is True:
            kept.append(item)
        else:
            dropped += 1
    return kept, dropped
