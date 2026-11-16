"""Monitoring — scheduled re-scans that detect change over time.

A watch re-runs an ordinary investigation on an interval and compares the new
result to the last one. When the public footprint changes (a new profile, a
new subdomain, something gone), it records a change event. This only re-calls
the same public-source investigators we already have — no new source, no
stored credentials, no covert tracking. It watches a target's *public* surface
the way anyone refreshing a page would, just on a timer.
"""

from __future__ import annotations

import hashlib
import json
import re

import store
from services.investigate import InvestigationValidationError, investigate
from tools.base import ToolError

# cap how many item keys we persist per watch, to bound the stored signature
MAX_ITEMS = 300

# "Label: value" parts of an info string that move on their own (counters,
# timestamps) and would report a change every check.
_VOLATILE_LABEL_RE = re.compile(
    r"^(followers?|following|stars?|forks?|repos?|public repos|posts?|karma|"
    r"rating|score|views?|subscribers?|members?|likes?|last (seen|active|online|"
    r"updated|post)|updated|online|status|rank|games|elo|uptime|response time)$",
    re.IGNORECASE,
)


def _stable_info(info) -> str:
    """The parts of an item's info worth watching (a new breach, a subdomain)."""
    parts = []
    for part in re.split(r";\s*", str(info or "")):
        label = part.split(":", 1)[0].strip() if ":" in part else ""
        if label and _VOLATILE_LABEL_RE.match(label):
            continue
        part = re.sub(r"\s+", " ", part).strip()
        if part:
            parts.append(part)
    return "; ".join(parts)


def signature_items(result: dict) -> list[str]:
    """Canonical, order-stable identity of a result's meaningful content.

    Each item is "platform|url|status", plus "|h:<hash>" of its stable info so
    a changed breach list or subdomain set is noticed. Web-search hits are left
    out: search engines reshuffle them between runs, which is not a change in
    the target's footprint.
    """
    items = []
    for item in (result.get("posts") or []) + (result.get("results") or []):
        if not isinstance(item, dict) or item.get("source") == "web_search" or (
            item.get("sources") == ["search-index"]
        ):
            continue
        platform = item.get("platform") or item.get("name") or item.get("site") or "?"
        url = item.get("url") or item.get("profile_url") or ""
        status = item.get("status") or ""
        key = f"{platform}|{url}|{status}"
        stable = _stable_info(item.get("info"))
        if stable:
            key += "|h:" + hashlib.sha256(stable.encode()).hexdigest()[:12]
        items.append(key)
    return sorted(set(items))[:MAX_ITEMS]


def _split(key: str) -> tuple[str, str | None]:
    """'platform|url|status|h:abc' -> ('platform|url|status', 'abc')."""
    base, sep, digest = key.rpartition("|h:")
    return (base, digest) if sep else (key, None)


def _diff_summary(old: list[str], new: list[str], allow_removed: bool = True) -> str | None:
    old_map = dict(_split(k) for k in old)
    new_map = dict(_split(k) for k in new)
    added = sorted(set(new_map) - set(old_map))
    removed = sorted(set(old_map) - set(new_map)) if allow_removed else []
    # an older baseline has no hashes (None): that is not a change
    changed = sorted(
        k for k in set(old_map) & set(new_map)
        if old_map[k] is not None and new_map[k] is not None and old_map[k] != new_map[k]
    )
    if not added and not removed and not changed:
        return None
    parts = []
    if added:
        parts.append(f"+{len(added)} new")
    if changed:
        parts.append(f"~{len(changed)} changed")
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
    if changed:
        detail.append("changed: " + _names(changed))
    if removed:
        detail.append("removed: " + _names(removed))
    return f"{head} ({'; '.join(detail)})"


async def check_watch(watch: dict) -> dict:
    """Run one watch, diff against its baseline, persist the outcome.

    Returns a small dict describing what happened (for the run-now endpoint).
    """
    watch_id = watch["id"]
    try:
        result = await investigate(watch["category"], watch["query"], fresh=True)
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

    old_raw = watch.get("last_hash")
    if not old_raw:
        store.record_watch_check(watch_id, json.dumps(new_items),
                                 f"baseline: {len(new_items)} items", None,
                                 expected_hash=old_raw)
        return {"status": "baseline", "items": len(new_items)}

    try:
        old_items = json.loads(old_raw)
    except (TypeError, ValueError):
        old_items = []

    # A source that failed this time (Sherlock timeout, GitHub limit) returns
    # nothing, which is not the same as its accounts disappearing: report no
    # removals and carry the previous items forward until a clean run.
    partial = bool(result.get("failed_sources"))
    if partial:
        new_bases = {_split(k)[0] for k in new_items}
        carried = [k for k in old_items if _split(k)[0] not in new_bases]
        new_items = sorted(set(new_items) | set(carried))[:MAX_ITEMS]
    summary = _diff_summary(old_items, new_items, allow_removed=not partial)
    status = "changed" if summary else "no change"
    if partial:
        status += " (partial: " + ", ".join(result["failed_sources"][:5]) + " failed)"
    # compare-and-set on the baseline: if another run (cron + "run now")
    # already recorded this change, this one does not log it twice
    applied = store.record_watch_check(watch_id, json.dumps(new_items), status,
                                       summary, expected_hash=old_raw)
    if not applied:
        return {"status": "skipped", "message": "another check of this watch finished first"}
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
