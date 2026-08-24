import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tools.base import ToolError
from tools.maigret_runner import run_maigret
from tools.sherlock_runner import run_sherlock

router = APIRouter(tags=["username"])

USERNAME_MIN_LENGTH = 2
USERNAME_MAX_LENGTH = 64
ALLOWED_USERNAME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


class UsernameRequest(BaseModel):
    query: str


def _validate(username: str) -> str | None:
    if not (
        USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH
    ) or not set(username) <= ALLOWED_USERNAME_CHARS:
        return (
            "Username must be 2-64 characters and contain only letters, digits, "
            "dots, underscores or hyphens."
        )
    return None


def _describe(tool_name: str, exc: BaseException) -> str:
    if isinstance(exc, ToolError):
        return f"{tool_name}: {exc}"
    return f"{tool_name}: unexpected error: {exc}"


def _merge(sherlock_results: list[dict], maigret_results: list[dict]) -> list[dict]:
    merged = {}
    ordered_entries = [("sherlock", entry) for entry in sherlock_results] + [
        ("maigret", entry) for entry in maigret_results
    ]
    for source, entry in ordered_entries:
        key = (entry["url"] or entry["platform"]).lower()
        if key in merged:
            if source not in merged[key]["sources"]:
                merged[key]["sources"].append(source)
        else:
            merged[key] = {
                "platform": entry["platform"],
                "url": entry["url"],
                "status": entry["status"],
                "sources": [source],
                **({"info": entry["info"]} if entry.get("info") else {}),
            }
    return sorted(merged.values(), key=lambda item: item["platform"].lower())


@router.post("/api/username")
async def search_username(request: UsernameRequest):
    username = request.query.strip().lstrip("@")
    validation_error = _validate(username)
    if validation_error:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": validation_error},
        )

    try:
        sherlock_outcome, maigret_outcome = await asyncio.gather(
            run_sherlock(username), run_maigret(username), return_exceptions=True
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Unexpected failure while running username tools: {exc}",
            },
        )

    errors = []
    sherlock_results = []
    maigret_results = []
    if isinstance(sherlock_outcome, BaseException):
        errors.append(_describe("Sherlock", sherlock_outcome))
    else:
        sherlock_results = sherlock_outcome["results"]
    if isinstance(maigret_outcome, BaseException):
        errors.append(_describe("Maigret", maigret_outcome))
    else:
        maigret_results = maigret_outcome["results"]

    results = _merge(sherlock_results, maigret_results)

    if not sherlock_results and not maigret_results and errors:
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "message": "; ".join(errors),
            },
        )

    response = {
        "status": "success",
        "query": username,
        "results": results,
        "count": len(results),
    }
    if errors:
        response["warnings"] = errors
    return response
