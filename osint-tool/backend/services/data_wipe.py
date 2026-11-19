"""Full deletion (ROADMAP 8.2): everything this tool stored about searches.

  - SQLite: cases, findings, watches, Agent runs (steps, decisions), and the
    audit log only when asked; secure_delete + VACUUM leave no copies behind
  - Redis: cached search answers (osint:*) and job results (arq:job:*,
    arq:result:*), which hold the same data for up to an hour
  - the in-process cache when Redis is not used

The downloaded public datasets (sanctions, registers) are not user data and
are kept.
"""
from __future__ import annotations

import asyncio
import logging

import store
from cache import clear_memory_cache, get_client

logger = logging.getLogger("osint.wipe")
REDIS_PATTERNS = ("osint:*", "arq:job:*", "arq:result:*")


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
    counts = await asyncio.to_thread(store.wipe_all, include_audit)
    clear_memory_cache()
    try:
        cached = await _wipe_redis()
        redis_error = None
    except Exception as exc:  # noqa: BLE001 - report it, the database part is already done
        logger.warning("redis wipe failed: %s", exc)
        cached, redis_error = 0, f"cache not cleared ({type(exc).__name__}); it expires within an hour"
    return {"deleted": counts, "cache_keys": cached, "warning": redis_error}
