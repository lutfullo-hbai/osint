from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from security import heavy_limit, limiter, verify_api_key
from services.investigate import (
    InvestigationValidationError,
    investigate_username,
)
from tools.base import ToolError

router = APIRouter(tags=["username"], dependencies=[Depends(verify_api_key)])


class UsernameRequest(BaseModel):
    query: str


@router.post("/api/username")
@limiter.limit(heavy_limit)
async def search_username(
    request: Request, response: Response, payload: UsernameRequest
):
    try:
        return await investigate_username(payload.query)
    except InvestigationValidationError as exc:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(exc)},
        )
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
                "message": f"Unexpected failure while running username tools: {exc}",
            },
        )
