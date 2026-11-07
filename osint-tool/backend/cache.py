import json
import logging
import os
import time
from typing import Any

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - redis is an optional runtime dependency
    redis_asyncio = None

REDIS_URL = os.environ.get("REDIS_URL", "").strip()
DEFAULT_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "900"))

logger = logging.getLogger("osint.cache")

_client = None
_memory: dict[str, tuple[float, str]] = {}


async def get_client():
    global _client
    if not REDIS_URL or redis_asyncio is None:
        return None
    if _client is None:
        _client = redis_asyncio.from_url(REDIS_URL, decode_responses=True)
    return _client


async def get_cached_json(key: str) -> Any | None:
    client = await get_client()
    if client is None:
        entry = _memory.get(key)
        if entry is None:
            return None
        expires_at, raw = entry
        if expires_at < time.time():
            _memory.pop(key, None)
            return None
        return json.loads(raw)

    try:
        raw = await client.get(key)
    except Exception as exc:  # pragma: no cover - depends on external service
        logger.warning("cache read failed: %s", exc)
        return None
    return json.loads(raw) if raw else None


async def set_cached_json(key: str, value: Any, ttl: int = DEFAULT_TTL_SECONDS) -> None:
    raw = json.dumps(value, ensure_ascii=False)
    client = await get_client()
    if client is None:
        _memory[key] = (time.time() + ttl, raw)
        return

    try:
        await client.set(key, raw, ex=ttl)
    except Exception as exc:  # pragma: no cover - depends on external service
        logger.warning("cache write failed: %s", exc)


def clear_memory_cache() -> None:
    _memory.clear()
