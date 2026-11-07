from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from security import limiter, light_limit, verify_api_key
from services.investigate import InvestigationValidationError, investigate_exposure
from tools.base import ToolError

router = APIRouter(tags=["exposure"], dependencies=[Depends(verify_api_key)])


class ExposureRequest(BaseModel):
    query: str


@router.post("/api/exposure")
@limiter.limit(light_limit)
async def search_exposure(request: Request, response: Response, payload: ExposureRequest):
    try:
        return await investigate_exposure(payload.query)
    except InvestigationValidationError as exc:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(exc)})
    except ToolError as exc:
        return JSONResponse(status_code=502, content={"status": "error", "message": str(exc)})
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Unexpected failure during exposure scan: {exc}"},
        )
