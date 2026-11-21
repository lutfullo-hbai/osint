import asyncio
import os
import time

from arq import cron
from arq.connections import RedisSettings

import store
from services.agent import execute_run
from services.data_wipe import was_wiped_since
from services.investigate import InvestigationValidationError, investigate
from services.monitor import check_one_watch, run_watch_cycle
from tools import sanctions_index, username_canary, uz_registry
from tools.holehe_runner import run_canary
from tools.maigret_db import ensure_db, run_self_check
from tools.base import ToolError

# how often the worker wakes to check for due watches (per-watch interval is
# enforced inside run_watch_cycle, so this is just the polling granularity)
WATCH_POLL_MINUTES = int(os.environ.get("WATCH_POLL_MINUTES", "5"))


async def run_investigation(ctx, category: str, query: str) -> dict:
    started = time.time()
    try:
        result = await investigate(category, query)
        if await was_wiped_since(started):
            # 8b.6: everything was deleted while this ran; do not keep the answer as a job result
            return {"status": "error", "message": "All stored data was deleted while this search ran."}
        return result
    except InvestigationValidationError as exc:
        return {"status": "error", "message": str(exc)}
    except ToolError as exc:
        return {"status": "error", "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "message": f"Unexpected failure: {exc}"}


async def run_agent(ctx, run_id: str) -> dict:
    """Agent mode: one free-text request, steps logged for the live view."""
    return await execute_run(run_id)


async def maigret_self_check(ctx) -> dict:
    """Weekly: rebuild our Maigret database and disable sites that broke."""
    try:
        return await run_self_check()
    except ToolError as exc:
        return {"status": "error", "message": str(exc)}


async def holehe_canary(ctx) -> dict:
    """Daily: pause Holehe modules that call a random address "registered"."""
    return await run_canary()


async def username_canary_check(ctx) -> dict:
    """Daily: find Sherlock/Maigret sites that "find" any username."""
    return await username_canary.run_canary()


async def sanctions_refresh(ctx) -> dict:
    """Daily: re-download the official sanctions lists that changed.

    PEPs are weekly, but if they never loaded (Wikidata rate limit) retry daily.
    """
    report = await sanctions_index.refresh_sources()
    if not sanctions_index.has_peps():
        report["pep"] = await sanctions_index.refresh_peps()
    return report


async def pep_refresh(ctx) -> dict:
    """Weekly: PEPs from Wikidata."""
    return await sanctions_index.refresh_peps()


async def uz_registry_refresh(ctx) -> dict:
    """Weekly: Uzbek official registers from data.egov.uz."""
    return await uz_registry.refresh()


async def _first_sanctions_build() -> None:
    await sanctions_index.refresh_sources()
    await sanctions_index.refresh_peps()


async def startup(ctx) -> None:
    store.init_db()
    ensure_db()
    if not (await username_canary.load()).get("tools"):
        ctx["username_canary"] = asyncio.create_task(username_canary.run_canary())
    if not uz_registry.dataset_status():
        ctx["uz_registry_build"] = asyncio.create_task(uz_registry.refresh())
    if not sanctions_index.source_status():
        # first run: build the index in the background, do not block startup
        ctx["sanctions_build"] = asyncio.create_task(_first_sanctions_build())


class WorkerSettings:
    functions = [run_investigation, check_one_watch, run_agent]
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
        cron(holehe_canary, hour=5, minute=15, run_at_startup=False, timeout=600),
        cron(username_canary_check, hour=5, minute=45, run_at_startup=False, timeout=900),
        cron(sanctions_refresh, hour=3, minute=30, run_at_startup=False, timeout=1800),
        cron(pep_refresh, weekday=6, hour=3, minute=0, run_at_startup=False, timeout=1800),
        cron(uz_registry_refresh, weekday=6, hour=4, minute=0, run_at_startup=False, timeout=1800),
    ]
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    max_jobs = int(os.environ.get("WORKER_MAX_JOBS", "4"))
    job_timeout = int(os.environ.get("WORKER_JOB_TIMEOUT", "1200"))
    keep_result = int(os.environ.get("WORKER_KEEP_RESULT", "3600"))
    max_tries = int(os.environ.get("WORKER_MAX_TRIES", "1"))
