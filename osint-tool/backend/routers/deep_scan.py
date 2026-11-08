from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from security import heavy_limit, limiter, verify_api_key
from services.deep_scan import run_deep_scan
from services.investigate import InvestigationValidationError
from tools.base import ToolError

router = APIRouter(tags=["deep-scan"], dependencies=[Depends(verify_api_key)])


class DeepScanRequest(BaseModel):
    query: str
    type: str | None = None


@router.post("/api/deep-scan")
@limiter.limit(heavy_limit)
async def deep_scan(request: Request, response: Response, payload: DeepScanRequest):
    try:
        return await run_deep_scan(payload.query, payload.type)
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
                "message": f"Unexpected failure during deep scan: {exc}",
            },
        )
