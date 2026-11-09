"""Monitoring — scheduled re-scans that detect change over time.

A watch re-runs an ordinary investigation on an interval and compares the new
result to the last one. When the public footprint changes (a new profile, a
new subdomain, something gone), it records a change event. This only re-calls
the same public-source investigators we already have — no new source, no
stored credentials, no covert tracking. It watches a target's *public* surface
the way anyone refreshing a page would, just on a timer.
"""

from __future__ import annotations

import json

import store
from services.investigate import InvestigationValidationError, investigate
from tools.base import ToolError

# cap how many item keys we persist per watch, to bound the stored signature
MAX_ITEMS = 300


def signature_items(result: dict) -> list[str]:
    """Canonical, order-stable identity of a result's meaningful content."""
    items = []
    for item in (result.get("posts") or []) + (result.get("results") or []):
        if not isinstance(item, dict):
            continue
        platform = item.get("platform") or item.get("name") or item.get("site") or "?"
        url = item.get("url") or item.get("profile_url") or ""
        status = item.get("status") or ""
        items.append(f"{platform}|{url}|{status}")
    return sorted(set(items))[:MAX_ITEMS]


def _diff_summary(old: list[str], new: list[str]) -> str | None:
    old_set, new_set = set(old), set(new)
    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)
    if not added and not removed:
        return None
    parts = []
    if added:
        parts.append(f"+{len(added)} new")
    if removed:
        parts.append(f"-{len(removed)} removed")
    head = ", ".join(parts)

    def _names(keys):
        return ", ".join(k.split("|", 1)[0] for k in keys[:5]) + (
            " ..." if len(keys) > 5 else ""
        )

    detail = []
    if added:
        detail.append("added: " + _names(added))
    if removed:
        detail.append("removed: " + _names(removed))
    return f"{head} ({'; '.join(detail)})"


async def check_watch(watch: dict) -> dict:
    """Run one watch, diff against its baseline, persist the outcome.

    Returns a small dict describing what happened (for the run-now endpoint).
    """
    watch_id = watch["id"]
    try:
        result = await investigate(watch["category"], watch["query"])
    except (InvestigationValidationError, ToolError) as exc:
        store.record_watch_check(watch_id, watch.get("last_hash"),
                                 f"error: {exc}", None)
        return {"status": "error", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - one watch must not sink the cycle
        store.record_watch_check(watch_id, watch.get("last_hash"),
                                 f"error: {exc}", None)
        return {"status": "error", "message": str(exc)}

    if result.get("status") != "success":
        store.record_watch_check(watch_id, watch.get("last_hash"),
                                 f"error: {result.get('message', 'failed')}", None)
        return {"status": "error", "message": result.get("message", "failed")}

    new_items = signature_items(result)
    new_hash = json.dumps(new_items)

    old_raw = watch.get("last_hash")
    if not old_raw:
        store.record_watch_check(watch_id, new_hash,
                                 f"baseline: {len(new_items)} items", None)
        return {"status": "baseline", "items": len(new_items)}

    try:
        old_items = json.loads(old_raw)
    except (TypeError, ValueError):
        old_items = []
    summary = _diff_summary(old_items, new_items)
    status = "changed" if summary else "no change"
    store.record_watch_check(watch_id, new_hash, status, summary)
    return {"status": status, "summary": summary, "items": len(new_items)}


async def check_one_watch(ctx, watch_id: str) -> dict:
    """arq entrypoint for an on-demand 'run now' of a single watch."""
    watch = store.get_watch(watch_id)
    return await check_watch(watch)


async def run_watch_cycle(ctx) -> dict:
    """arq cron entrypoint — check every watch whose interval has elapsed."""
    due = store.due_watches()
    checked = 0
    changed = 0
    for watch in due:
        outcome = await check_watch(watch)
        checked += 1
        if outcome.get("status") == "changed":
            changed += 1
    return {"checked": checked, "changed": changed}
