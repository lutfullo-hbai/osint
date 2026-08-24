import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tools.base import ToolError
from tools.name_search import run_name_search

router = APIRouter(tags=["name"])

ALLOWED_NAME_PUNCTUATION = set(" '-.")


class NameRequest(BaseModel):
    query: str


def _validate(raw_name: str) -> str | None:
    if not (3 <= len(raw_name) <= 80):
        return "Name must be between 3 and 80 characters."
    letter_count = sum(1 for char in raw_name if char.isalpha())
    if letter_count < 2:
        return "Name must contain at least two letters."
    if not all(
        char.isalpha() or char in ALLOWED_NAME_PUNCTUATION for char in raw_name
    ):
        return (
            "Name may only contain letters, spaces, apostrophes, "
            "hyphens and dots."
        )
    return None


@router.post("/api/name")
async def search_name(request: NameRequest):
    name = re.sub(r"\s+", " ", request.query.strip())
    validation_error = _validate(name)
    if validation_error:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": validation_error},
        )

    try:
        outcome = await run_name_search(name)
    except ToolError as exc:
        return JSONResponse(
            status_code=502,
            content={"status": "error", "message": str(exc)},
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Unexpected failure during name search: {exc}",
            },
        )

    results = outcome["results"]
    response = {
        "status": "success",
        "query": name,
        "results": results,
        "count": len(results),
    }
    if not results:
        response["message"] = (
            "No publicly indexed profiles found for this exact name. "
            "Try quoting a nickname instead of the full name."
        )
    return response
