from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from security import limiter, light_limit, verify_api_key
from services.investigate import InvestigationValidationError, investigate_domain
from tools.base import ToolError

router = APIRouter(tags=["domain"], dependencies=[Depends(verify_api_key)])


class DomainRequest(BaseModel):
    query: str


@router.post("/api/domain")
@limiter.limit(light_limit)
async def search_domain(request: Request, response: Response, payload: DomainRequest):
    try:
        return await investigate_domain(payload.query)
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
                "message": f"Unexpected failure during domain lookup: {exc}",
            },
        )
