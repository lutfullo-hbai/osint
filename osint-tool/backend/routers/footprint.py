from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from security import heavy_limit, limiter, verify_api_key
from services.investigate import InvestigationValidationError, investigate_footprint
from tools.base import ToolError

router = APIRouter(tags=["footprint"], dependencies=[Depends(verify_api_key)])


class FootprintRequest(BaseModel):
    query: str


@router.post("/api/footprint")
@limiter.limit(heavy_limit)
async def search_footprint(request: Request, response: Response, payload: FootprintRequest):
    try:
        return await investigate_footprint(payload.query)
    except InvestigationValidationError as exc:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(exc)})
    except ToolError as exc:
        return JSONResponse(status_code=502, content={"status": "error", "message": str(exc)})
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Unexpected failure during footprint scan: {exc}"},
        )
