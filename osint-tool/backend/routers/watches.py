import asyncio
import os

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import store
from security import general_limit, limiter, verify_api_key
from services.investigate import CATEGORIES
from services.monitor import check_one_watch

router = APIRouter(tags=["watches"], dependencies=[Depends(verify_api_key)])

REDIS_URL = os.environ.get("REDIS_URL", "").strip()
_pool = None


async def _get_pool():
    global _pool
    if not REDIS_URL:
        return None
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
    return _pool


class WatchRequest(BaseModel):
    name: str
    category: str
    query: str
    interval_minutes: int = 60


class ActiveRequest(BaseModel):
    active: bool


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"status": "error", "message": message})


@router.post("/api/watches")
@limiter.limit(general_limit)
async def create_watch(request: Request, response: Response, payload: WatchRequest):
    category = payload.category.strip().lower()
    if category not in CATEGORIES:
        return _error(400, f"Unknown category '{payload.category}'. Choose one of: "
                      + ", ".join(CATEGORIES) + ".")
    try:
        watch = await asyncio.to_thread(
            store.create_watch, payload.name, category, payload.query,
            payload.interval_minutes,
        )
        return {"status": "success", "watch": watch}
    except store.CaseError as exc:
        return _error(400, str(exc))


@router.get("/api/watches")
@limiter.limit(general_limit)
async def list_watches(request: Request, response: Response):
    watches = await asyncio.to_thread(store.list_watches)
    return {"status": "success", "watches": watches}


@router.get("/api/watches/{watch_id}")
@limiter.limit(general_limit)
async def get_watch(request: Request, response: Response, watch_id: str):
    try:
        return {"status": "success", "watch": await asyncio.to_thread(store.get_watch, watch_id)}
    except store.CaseError as exc:
        return _error(404, str(exc))


@router.patch("/api/watches/{watch_id}")
@limiter.limit(general_limit)
async def toggle_watch(request: Request, response: Response, watch_id: str,
                       payload: ActiveRequest):
    try:
        watch = await asyncio.to_thread(store.set_watch_active, watch_id, payload.active)
        return {"status": "success", "watch": watch}
    except store.CaseError as exc:
        return _error(404, str(exc))


@router.delete("/api/watches/{watch_id}")
@limiter.limit(general_limit)
async def delete_watch(request: Request, response: Response, watch_id: str):
    try:
        await asyncio.to_thread(store.delete_watch, watch_id)
        return {"status": "success"}
    except store.CaseError as exc:
        return _error(404, str(exc))


@router.post("/api/watches/{watch_id}/run")
@limiter.limit(general_limit)
async def run_watch(request: Request, response: Response, watch_id: str):
    try:
        watch = await asyncio.to_thread(store.get_watch, watch_id)
    except store.CaseError as exc:
        return _error(404, str(exc))
    pool = await _get_pool()
    if pool is not None:
        await pool.enqueue_job("check_one_watch", watch_id)
        return {"status": "success", "queued": True,
                "message": "Check queued; the worker will run it shortly."}
    # no queue (dev) — run inline so the feature still works
    outcome = await check_one_watch(None, watch_id)
    return {"status": "success", "queued": False, "result": outcome}
