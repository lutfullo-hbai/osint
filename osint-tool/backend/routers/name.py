from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from security import limiter, light_limit, verify_api_key
from services.investigate import InvestigationValidationError, investigate_name
from tools.base import ToolError

router = APIRouter(tags=["name"], dependencies=[Depends(verify_api_key)])


class NameRequest(BaseModel):
    query: str


@router.post("/api/name")
@limiter.limit(light_limit)
async def search_name(request: Request, response: Response, payload: NameRequest):
    try:
        return await investigate_name(payload.query)
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
                "message": f"Unexpected failure during name search: {exc}",
            },
        )
