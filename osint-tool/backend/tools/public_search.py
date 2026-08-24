import asyncio
import re
import time

from urllib.parse import urlparse

import httpx

from tools.base import ToolError

SEARCH_TIMEOUT_SECONDS = 150
DEFAULT_MAX_RESULTS = 15
DELAY_BETWEEN_BATCHES_SECONDS = 2.5

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


async def search_public(
    query_batches: list[str],
    timeout: int = SEARCH_TIMEOUT_SECONDS,
    max_results_per_batch: int = DEFAULT_MAX_RESULTS,
) -> list[dict]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _search_sync, list(query_batches), max_results_per_batch
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise ToolError(
            f"Public search timed out after {timeout} seconds"
        ) from None
    except ToolError:
        raise
    except ImportError:
        raise ToolError("'ddgs' package is not installed on the server") from None
    except Exception as exc:
        raise ToolError(f"Public search failed unexpectedly: {exc}") from exc


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
                response = await client.get(url)
            except httpx.HTTPError:
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
        follow_redirects=True,
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
