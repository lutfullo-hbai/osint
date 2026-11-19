"""False-positive filter for Sherlock and Maigret.

Some sites answer "this user exists" for ANY name (catch-all pages, WAF or
login walls that block our IP). A live test showed Sherlock "finding" the
same 42 sites for a made-up handle. Once a day we check a random handle nobody
has registered; every site that reports it as found is producing false
positives, and its hits are ignored until the next check. Needs no real
person's data (same idea as the Holehe canary).
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time

from cache import get_cached_json, set_cached_json

KEY = "osint:username_canary"
TTL_SECONDS = 3 * 24 * 3600        # a stale list is better than none if a daily run fails
TOOLS = ("sherlock", "maigret")

log = logging.getLogger(__name__)


def _key(platform: str) -> str:
    return str(platform or "").strip().casefold()


async def load() -> dict:
    return await get_cached_json(KEY) or {}


async def false_positive_sites() -> dict[str, set[str]]:
    data = await load()
    return {tool: set(data.get("tools", {}).get(tool) or []) for tool in TOOLS}


def drop_false_positives(results: list[dict], sites: set[str]) -> tuple[list[dict], int]:
    if not sites:
        return results, 0
    kept = [r for r in results if _key(r.get("platform")) not in sites]
    return kept, len(results) - len(kept)


async def run_canary() -> dict:
    """Ask both tools about a random handle; remember who says it exists."""
    from tools.maigret_runner import run_maigret
    from tools.sherlock_runner import run_sherlock

    handle = "nx" + secrets.token_hex(7)
    previous = (await load()).get("tools", {})
    outcomes = await asyncio.gather(run_sherlock(handle), run_maigret(handle), return_exceptions=True)
    tools, report = {}, {"handle": handle}
    for tool, outcome in zip(TOOLS, outcomes):
        if isinstance(outcome, BaseException):
            log.warning("username canary: %s failed: %s", tool, outcome)
            tools[tool] = previous.get(tool) or []        # keep the last good list
            report[tool] = f"failed: {type(outcome).__name__}"
            continue
        tools[tool] = sorted({_key(r.get("platform")) for r in outcome.get("results") or []} - {""})
        report[tool] = len(tools[tool])
    await set_cached_json(KEY, {"at": time.time(), "handle": handle, "tools": tools}, TTL_SECONDS)
    return report
