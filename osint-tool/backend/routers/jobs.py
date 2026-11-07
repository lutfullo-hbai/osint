import os

from arq import create_pool
from arq.connections import RedisSettings
from arq.jobs import Job, JobStatus
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from security import heavy_limit, limiter, poll_limit, verify_api_key
from services.investigate import CATEGORIES

router = APIRouter(tags=["jobs"], dependencies=[Depends(verify_api_key)])

REDIS_URL = os.environ.get("REDIS_URL", "").strip()

_pool = None


async def _get_pool():
    global _pool
    if not REDIS_URL:
        return None
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
    return _pool


def _queue_disabled_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "status": "error",
            "message": (
                "Job queue is disabled. Set REDIS_URL and start the worker "
                "service to enable asynchronous jobs."
            ),
        },
    )


class JobRequest(BaseModel):
    category: str
    query: str


@router.post("/api/jobs")
@limiter.limit(heavy_limit)
async def create_job(request: Request, response: Response, payload: JobRequest):
    category = payload.category.strip().lower()
    query = payload.query.strip()

    if category not in CATEGORIES:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": (
                    f"Unknown category '{payload.category}'. Choose one of: "
                    + ", ".join(CATEGORIES)
                    + "."
                ),
            },
        )
    if not query:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Query must not be empty."},
        )

    pool = await _get_pool()
    if pool is None:
        return _queue_disabled_response()

    job = await pool.enqueue_job("run_investigation", category, query)
    if job is None:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "message": "Could not enqueue the job."},
        )

    return {
        "status": "queued",
        "job_id": job.job_id,
        "category": category,
        "query": query,
    }


@router.get("/api/jobs/{job_id}")
@limiter.limit(poll_limit)
async def get_job(request: Request, response: Response, job_id: str):
    pool = await _get_pool()
    if pool is None:
        return _queue_disabled_response()

    job = Job(job_id, pool)
    status = await job.status()

    if status == JobStatus.not_found:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Job not found."},
        )

    if status == JobStatus.complete:
        try:
            result = await job.result(timeout=1)
        except Exception as exc:
            return {
                "status": "failed",
                "job_id": job_id,
                "message": f"Job finished without a usable result: {exc}",
            }
        return {
            "status": "complete",
            "job_id": job_id,
            "result": result,
        }

    return {
        "status": getattr(status, "value", str(status)),
        "job_id": job_id,
    }
