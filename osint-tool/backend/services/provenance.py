"""Provenance of every value (ROADMAP 8.1, ZRU-547 art. 30).

Each search result already names its source (platform + url). Here every
result also gets the moment it was retrieved, stamped once when the source
answered. A cached answer keeps its original time, so a result read from the
cache an hour later still says when the source was really asked.
"""
from __future__ import annotations

from datetime import datetime, timezone

MAX_DEPTH = 6


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _walk(value, at: str, depth: int) -> None:
    if depth > MAX_DEPTH:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "results" and isinstance(child, list):
                for item in child:
                    if isinstance(item, dict):
                        item.setdefault("retrieved_at", at)
                        _walk(item, at, depth + 1)
            elif isinstance(child, (dict, list)):
                _walk(child, at, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _walk(child, at, depth + 1)


def stamp(result, at: str | None = None):
    """Set retrieved_at on the response and on every item of each "results"
    list inside it (nested sections too). Existing stamps are kept."""
    if not isinstance(result, dict):
        return result
    at = at or now_iso()
    result.setdefault("retrieved_at", at)
    _walk(result, result["retrieved_at"], 0)
    return result
