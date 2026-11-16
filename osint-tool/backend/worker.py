import os

from arq import cron
from arq.connections import RedisSettings

import store
from services.investigate import InvestigationValidationError, investigate
from services.monitor import check_one_watch, run_watch_cycle
from tools.maigret_db import ensure_db, run_self_check
from tools.base import ToolError

# how often the worker wakes to check for due watches (per-watch interval is
# enforced inside run_watch_cycle, so this is just the polling granularity)
WATCH_POLL_MINUTES = int(os.environ.get("WATCH_POLL_MINUTES", "5"))


async def run_investigation(ctx, category: str, query: str) -> dict:
    try:
        return await investigate(category, query)
    except InvestigationValidationError as exc:
        return {"status": "error", "message": str(exc)}
    except ToolError as exc:
        return {"status": "error", "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "message": f"Unexpected failure: {exc}"}


async def maigret_self_check(ctx) -> dict:
    """Weekly: rebuild our Maigret database and disable sites that broke."""
    try:
        return await run_self_check()
    except ToolError as exc:
        return {"status": "error", "message": str(exc)}


async def startup(ctx) -> None:
    store.init_db()
    ensure_db()


class WorkerSettings:
    functions = [run_investigation, check_one_watch]
    on_startup = startup
    cron_jobs = [
        cron(
            run_watch_cycle,
            minute=set(range(0, 60, max(1, min(WATCH_POLL_MINUTES, 59)))),
            run_at_startup=False,
        ),
        # Monday 04:30 UTC: a long job, kept away from working hours
        cron(maigret_self_check, weekday=0, hour=4, minute=30, run_at_startup=False,
             timeout=2400),
    ]
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    max_jobs = int(os.environ.get("WORKER_MAX_JOBS", "4"))
    job_timeout = int(os.environ.get("WORKER_JOB_TIMEOUT", "1200"))
    keep_result = int(os.environ.get("WORKER_KEEP_RESULT", "3600"))
    max_tries = int(os.environ.get("WORKER_MAX_TRIES", "1"))
