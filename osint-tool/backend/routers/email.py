from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from security import heavy_limit, limiter, verify_api_key
from services.investigate import InvestigationValidationError, investigate_email
from tools.base import ToolError

router = APIRouter(tags=["email"], dependencies=[Depends(verify_api_key)])


class EmailRequest(BaseModel):
    query: str


@router.post("/api/email")
@limiter.limit(heavy_limit)
async def search_email(request: Request, response: Response, payload: EmailRequest):
    try:
        return await investigate_email(payload.query)
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
                "message": f"Unexpected failure while running Holehe: {exc}",
            },
        )
