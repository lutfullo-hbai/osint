"""Full deletion (ROADMAP 8.2): everything this tool stored about searches.

  - SQLite: cases, findings, watches, Agent runs (steps, decisions), and the
    audit log only when asked; secure_delete + VACUUM leave no copies behind
  - Redis: cached search answers (osint:*, up to 24 hours) and job results
    (arq:job:*, arq:result:*, arq:retry:*)
  - the passive-DNS store: every domain in it was searched by someone
  - the in-process cache when Redis is not used

A search still running when this happens would write its answer back
afterwards; the time of the wipe is kept (WIPED_AT_KEY) and such an answer
is not cached or stored (see was_wiped_since).

The downloaded public datasets (sanctions, registers) are not user data and
are kept.
"""
from __future__ import annotations

import asyncio
import logging
import time

import store
from cache import clear_memory_cache, get_client
from tools import passive_dns

logger = logging.getLogger("osint.wipe")
REDIS_PATTERNS = ("osint:*", "arq:job:*", "arq:result:*", "arq:retry:*")
WIPED_AT_KEY = "osint-meta:wiped_at"     # not matched by "osint:*"
_wiped_at_local = 0.0                    # without Redis (single process)


async def _mark_wiped() -> None:
    global _wiped_at_local
    _wiped_at_local = time.time()
    client = await get_client()
    if client is not None:
        await client.set(WIPED_AT_KEY, str(_wiped_at_local))


async def was_wiped_since(started: float) -> bool:
    """True if a full deletion happened after `started` (time.time())."""
    wiped = _wiped_at_local
    try:
        client = await get_client()
        if client is not None:
            wiped = max(wiped, float(await client.get(WIPED_AT_KEY) or 0))
    except Exception:  # noqa: BLE001 - unknown means "not wiped": the answer is kept
        pass
    return wiped >= started


async def _wipe_redis() -> int:
    client = await get_client()
    if client is None:
        return 0
    removed = 0
    for pattern in REDIS_PATTERNS:
        batch = []
        async for key in client.scan_iter(match=pattern, count=500):
            batch.append(key)
            if len(batch) >= 500:
                removed += await client.delete(*batch)
                batch = []
        if batch:
            removed += await client.delete(*batch)
    return removed


async def wipe_everything(include_audit: bool = False) -> dict:
    """Every step runs even if an earlier one fails; failures become warnings."""
    warnings: list[str] = []
    try:
        await _mark_wiped()
    except Exception as exc:  # noqa: BLE001
        logger.warning("wipe marker failed: %s", exc)
    try:
        db = await asyncio.to_thread(store.wipe_all, include_audit)
        counts, warnings = db["deleted"], list(db["warnings"])
    except Exception as exc:  # noqa: BLE001 - keep going: the cache must still be cleared
        logger.warning("database wipe failed: %s", exc)
        counts = {}
        warnings.append(f"cases database not cleared ({type(exc).__name__}); try again")
    try:
        counts["passive_dns"] = await asyncio.to_thread(passive_dns.wipe)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"passive-DNS store not cleared ({type(exc).__name__})")
    clear_memory_cache()
    cached = 0
    try:
        cached = await _wipe_redis()
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis wipe failed: %s", exc)
        warnings.append(f"cache not cleared ({type(exc).__name__}); cached answers expire within 24 hours")
    return {"deleted": counts, "cache_keys": cached,
            "warning": "; ".join(warnings) or None, "warnings": warnings}
