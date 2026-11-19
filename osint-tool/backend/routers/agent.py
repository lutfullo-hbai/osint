"""Agent mode API (ROADMAP Faza 6).

POST /api/agent                      {text} -> run id; work runs in the worker
GET  /api/agent/{id}?after=N         status, steps after N (live view), result
POST /api/agent/{id}/decision        {candidate_id, decision, note} — the human's call
GET  /api/agent                      recent runs
GET  /api/agent/{id}/card/{cid}[/pdf] person card of one candidate (7.1)
GET  /api/agent/{id}/graph?format=    GraphML or Maltego CSV of the run's graph (7.8)
Without Redis the run executes in this process in the background instead.
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import store
from routers.jobs import _get_pool
from security import general_limit, heavy_limit, limiter, poll_limit, verify_api_key
from routers.export import graph_file
from services.agent import execute_run
from services.person_card import CardError, build_card, card_pdf

router = APIRouter(tags=["agent"], dependencies=[Depends(verify_api_key)])
log = logging.getLogger(__name__)

# a run with no new step for this long has died (worker restart, crash)
STALE_AFTER = timedelta(minutes=25)
_local_tasks: set[asyncio.Task] = set()


class AgentRequest(BaseModel):
    text: str


class DecisionRequest(BaseModel):
    candidate_id: str
    decision: str
    note: str = ""


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"status": "error", "message": message})


@router.post("/api/agent")
@limiter.limit(heavy_limit)
async def start_agent(request: Request, response: Response, payload: AgentRequest):
    try:
        run = await asyncio.to_thread(store.create_agent_run, payload.text)
    except store.CaseError as exc:
        return _error(400, str(exc))
    pool = None
    try:
        pool = await _get_pool()
    except Exception as exc:  # noqa: BLE001 - fall back to in-process
        log.warning("job queue unavailable, running agent in-process: %s", exc)
    if pool is not None and await pool.enqueue_job("run_agent", run["id"]) is not None:
        mode = "worker"
    else:
        task = asyncio.create_task(execute_run(run["id"]))
        _local_tasks.add(task)
        task.add_done_callback(_local_tasks.discard)
        mode = "local"
    return {"status": "queued", "run_id": run["id"], "mode": mode}


@router.get("/api/agent")
@limiter.limit(general_limit)
async def list_runs(request: Request, response: Response, limit: int = 20):
    return {"status": "success", "runs": await asyncio.to_thread(store.list_agent_runs, limit)}


@router.get("/api/agent/{run_id}")
@limiter.limit(poll_limit)
async def get_run(request: Request, response: Response, run_id: str, after: int = 0):
    try:
        run = await asyncio.to_thread(store.get_agent_run, run_id, max(0, after))
    except store.CaseError as exc:
        return _error(404, str(exc))
    if run["status"] in ("queued", "running"):
        updated = datetime.fromisoformat(run["updated_at"])
        if datetime.now(timezone.utc) - updated > STALE_AFTER:
            message = "The run stopped responding (worker restarted?). Start it again."
            await asyncio.to_thread(store.update_agent_run, run_id, status="failed", error=message)
            run["status"], run["error"] = "failed", message
    if after and run["status"] != "complete":
        run["result"] = None            # polling: only the new steps until it is done
    return {"status": "success", "run": run}


@router.post("/api/agent/{run_id}/decision")
@limiter.limit(general_limit)
async def decide(request: Request, response: Response, run_id: str, payload: DecisionRequest):
    try:
        decision = await asyncio.to_thread(store.set_agent_decision, run_id, payload.candidate_id,
                                           payload.decision, payload.note)
    except store.CaseError as exc:
        return _error(404 if "not found" in str(exc) else 400, str(exc))
    return {"status": "success", "decision": decision}


async def _run_or_404(run_id: str):
    try:
        return await asyncio.to_thread(store.get_agent_run, run_id), None
    except store.CaseError as exc:
        return None, _error(404, str(exc))


@router.get("/api/agent/{run_id}/card/{candidate_id}")
@limiter.limit(general_limit)
async def person_card(request: Request, response: Response, run_id: str, candidate_id: str):
    """ROADMAP 7.1: one candidate as a person card (JSON)."""
    run, error = await _run_or_404(run_id)
    if error:
        return error
    try:
        return {"status": "success", "card": build_card(run, candidate_id)}
    except CardError as exc:
        return _error(404, str(exc))


@router.get("/api/agent/{run_id}/card/{candidate_id}/pdf")
@limiter.limit(heavy_limit)
async def person_card_pdf(request: Request, response: Response, run_id: str, candidate_id: str):
    run, error = await _run_or_404(run_id)
    if error:
        return error
    try:
        card = build_card(run, candidate_id)
    except CardError as exc:
        return _error(404, str(exc))
    pdf = await asyncio.to_thread(card_pdf, card)
    label = re.sub(r"[^A-Za-z0-9._-]+", "_", str(card["candidate"].get("label") or "person")).strip("_")[:50]
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="person-card-{label or "person"}.pdf"'})


@router.get("/api/agent/{run_id}/graph")
@limiter.limit(general_limit)
async def agent_graph(request: Request, response: Response, run_id: str, format: str = "graphml"):
    """ROADMAP 7.8: the run's link graph for Gephi/yEd (GraphML) or Maltego CE (CSV)."""
    run, error = await _run_or_404(run_id)
    if error:
        return error
    scan = (run.get("result") or {}).get("scan")
    if not scan:
        return _error(409, "The run has no graph yet.")
    return graph_file(scan, format, f"agent-{run_id[:8]}")
