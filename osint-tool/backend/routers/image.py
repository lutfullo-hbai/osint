from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from security import heavy_limit, limiter, verify_api_key
from services.investigate import InvestigationValidationError, investigate_image
from tools.base import ToolError

router = APIRouter(tags=["image"], dependencies=[Depends(verify_api_key)])


class ImageRequest(BaseModel):
    query: str


@router.post("/api/image")
@limiter.limit(heavy_limit)
async def search_image(request: Request, response: Response, payload: ImageRequest):
    try:
        return await investigate_image(payload.query)
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
                "message": f"Unexpected failure during image analysis: {exc}",
            },
        )
