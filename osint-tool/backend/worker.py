import os

from arq.connections import RedisSettings

from services.investigate import InvestigationValidationError, investigate
from tools.base import ToolError


async def run_investigation(ctx, category: str, query: str) -> dict:
    try:
        return await investigate(category, query)
    except InvestigationValidationError as exc:
        return {"status": "error", "message": str(exc)}
    except ToolError as exc:
        return {"status": "error", "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "message": f"Unexpected failure: {exc}"}


class WorkerSettings:
    functions = [run_investigation]
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    max_jobs = int(os.environ.get("WORKER_MAX_JOBS", "4"))
    job_timeout = int(os.environ.get("WORKER_JOB_TIMEOUT", "1200"))
    keep_result = int(os.environ.get("WORKER_KEEP_RESULT", "3600"))
    max_tries = int(os.environ.get("WORKER_MAX_TRIES", "1"))
