"""Source health: which backends work right now, and why one might not."""
import asyncio
import os
import shutil
import time

import httpx
from fastapi import APIRouter, Depends, Request, Response

from security import general_limit, limiter, verify_api_key
from tools import holehe_runner, maigret_db, public_search, sanctions_index, truecaller, uz_registry

router = APIRouter(tags=["sources"], dependencies=[Depends(verify_api_key)])

KEYS = ["BRAVE_API_KEY", "GITHUB_TOKEN", "COMPANIES_HOUSE_API_KEY", "HIBP_API_KEY", "SECURITYTRAILS_API_KEY",
        "HUNTER_API_KEY", "OPENSANCTIONS_API_KEY", "OPENCORPORATES_API_KEY"]


async def _searxng(client: httpx.AsyncClient) -> dict:
    base = os.environ.get("SEARXNG_URL", "").strip().rstrip("/")
    if not base:
        return {"ok": False, "detail": "not configured (SEARXNG_URL)"}
    try:
        response = await client.get(f"{base}/healthz", timeout=5)
        return {"ok": response.status_code == 200, "detail": f"HTTP {response.status_code}"}
    except httpx.HTTPError as exc:
        return {"ok": False, "detail": type(exc).__name__}


async def _github(client: httpx.AsyncClient) -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        # /rate_limit itself does not count against the limit
        response = await client.get("https://api.github.com/rate_limit", headers=headers, timeout=8)
        core = response.json().get("resources", {}).get("core", {})
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "detail": type(exc).__name__}
    remaining, limit = core.get("remaining", 0), core.get("limit", 0)
    reset_in = max(0, int(core.get("reset", time.time()) - time.time()) // 60)
    return {"ok": remaining > 0, "detail": f"{remaining}/{limit} requests left, resets in {reset_in} min",
            "token": bool(token)}


def _maigret() -> dict:
    path = maigret_db.DB_PATH
    if not os.path.exists(path):
        return {"ok": True, "detail": "bundled database (custom copy not built yet)"}
    age_days = (time.time() - os.path.getmtime(path)) / 86400
    return {"ok": True, "detail": f"custom database, {maigret_db.disabled_count(path)} sites disabled, "
                                  f"updated {age_days:.0f} day(s) ago"}


async def _engine_summary() -> str:
    """'; engines: brave 98% ok, google blocked (access denied)...'"""
    stats = await public_search.engine_stats()
    if not stats:
        return ""
    parts = []
    for engine, row in sorted(stats.items(), key=lambda kv: -(kv[1].get("ok", 0))):
        total = row.get("ok", 0) + row.get("fail", 0)
        if not total:
            continue
        share = row.get("ok", 0) / total
        parts.append(f"{engine} {share:.0%} ok" if share >= 0.5 else
                     f"{engine} failing ({row.get('last_error', '?')})")
    return "; engines: " + ", ".join(parts[:10]) if parts else ""


def _uz_registry() -> dict:
    status = uz_registry.dataset_status()
    if not status:
        return {"ok": False, "detail": "not built yet (the worker builds it on first start)"}
    total = sum(r.get("rows") or 0 for r in status.values())
    oldest = max((time.time() - (r.get("fetched_at") or 0)) / 86400 for r in status.values())
    truncated = [k for k, r in status.items() if r.get("truncated")]
    return {"ok": True, "detail": f"{len(status)} registers, {total} records, oldest {oldest:.0f}d"
                                  + (f"; portal-truncated: {', '.join(truncated)}" if truncated else "")}


def _sanctions() -> dict:
    status = sanctions_index.source_status()
    if not status:
        return {"ok": False, "detail": "not built yet (the worker builds it on first start)"}
    parts = []
    for key, row in sorted(status.items()):
        age = (time.time() - (row.get("fetched_at") or 0)) / 86400
        parts.append(f"{key.upper()} {row.get('records', 0)} ({age:.0f}d)")
    return {"ok": True, "detail": "; ".join(parts)}


async def _holehe() -> dict:
    try:
        h = await holehe_runner.health_summary()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": type(exc).__name__}
    active = h["allowed"] - len(h["paused"])
    detail = (f"{active} sign-up checks active, {len(h['paused'])} paused, "
              f"{h['excluded_by_policy']} excluded (password recovery / login / adult)")
    if h["paused"]:
        detail += "; paused: " + ", ".join(sorted(h["paused"])[:10])
    return {"ok": active > 0, "detail": detail, "paused": h["paused"]}


@router.get("/api/sources/health")
@limiter.limit(general_limit)
async def sources_health(request: Request, response: Response):
    async with httpx.AsyncClient() as client:
        searxng, github = await asyncio.gather(_searxng(client), _github(client))
    order = (["Brave API"] if os.environ.get("BRAVE_API_KEY", "").strip() else []) + (
        ["SearXNG"] if os.environ.get("SEARXNG_URL", "").strip() else []) + ["DuckDuckGo"]
    tc_until = truecaller._unreachable_until - time.monotonic()
    sources = {
        "Web search": {"ok": searxng["ok"] or len(order) > 1,
                       "detail": "order: " + " → ".join(order)},
        "SearXNG": {**searxng, "detail": searxng["detail"] + await _engine_summary()},
        "GitHub API": github,
        "Maigret": await asyncio.to_thread(_maigret),
        "Subfinder": {"ok": shutil.which("subfinder") is not None,
                      "detail": "installed" if shutil.which("subfinder") else "binary missing"},
        "Holehe": await _holehe(),
        "Sanctions index": await asyncio.to_thread(_sanctions),
        "UZ registers": await asyncio.to_thread(_uz_registry),
        "Truecaller": {"ok": tc_until <= 0,
                       "detail": "available" if tc_until <= 0 else f"skipped for {int(tc_until // 60) + 1} min (unreachable)"},
    }
    return {
        "status": "success",
        "sources": sources,
        "keys": {key: bool(os.environ.get(key, "").strip()) for key in KEYS},
    }
