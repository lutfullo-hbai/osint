"""Access, audit and deletion (ROADMAP 8.2-8.4, 8b).

GET    /api/whoami    which user this key acts as
GET    /api/audit     who searched what and when (admin)
DELETE /api/data      delete everything stored, {"confirm": "DELETE ALL"} (admin)
"""
import asyncio
import os

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import store
from security import (
    ADMIN,
    LOCAL,
    configured_users,
    general_limit,
    heavy_limit,
    limiter,
    require_admin,
    verify_api_key,
)
from services.data_wipe import wipe_everything

router = APIRouter(tags=["audit"])
CONFIRM_PHRASE = "DELETE ALL"


def _allowed_origins() -> set[str]:
    return {o.strip().rstrip("/") for o in os.environ.get(
        "ALLOWED_ORIGINS", "http://127.0.0.1:8080,http://localhost:8080").split(",") if o.strip()}


class WipeRequest(BaseModel):
    confirm: str = ""
    include_audit: bool = False


@router.get("/api/whoami")
@limiter.limit(general_limit)
async def whoami(request: Request, response: Response, user: str = Depends(verify_api_key)):
    return {"user": user, "admin": user in (ADMIN, LOCAL), "keys_configured": bool(configured_users()),
            "audit_retention_days": store.AUDIT_RETENTION_DAYS}


@router.get("/api/audit")
@limiter.limit(general_limit)
async def audit(request: Request, response: Response, limit: int = 100, user: str = "",
                q: str = "", before: int = 0, _admin: str = Depends(require_admin)):
    entries = await asyncio.to_thread(store.list_audit, limit, user.strip(), q.strip()[:100], before)
    return {"entries": entries, "retention_days": store.AUDIT_RETENTION_DAYS}


@router.delete("/api/data")
@limiter.limit(heavy_limit)
async def wipe(request: Request, response: Response, payload: WipeRequest,
               _admin: str = Depends(require_admin)):
    origin = (request.headers.get("origin") or "").rstrip("/")
    if not configured_users() and origin and origin not in _allowed_origins():
        # 8b.1: without keys, only the console itself may start a full deletion
        return JSONResponse(status_code=403, content={
            "status": "error", "message": "Full deletion is only allowed from the NEXUS console."})
    if payload.confirm.strip() != CONFIRM_PHRASE:
        return JSONResponse(status_code=400, content={
            "status": "error", "message": f'Type "{CONFIRM_PHRASE}" to confirm.'})
    return {"status": "deleted", **await wipe_everything(payload.include_audit)}
