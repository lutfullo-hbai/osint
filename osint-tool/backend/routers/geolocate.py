"""Image geolocation API: upload (or URL) -> ranked place candidates on a map."""
import httpx
from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from security import heavy_limit, light_limit, limiter, verify_api_key
from services import geolocate
from services.investigate import InvestigationValidationError, normalize_image_url
from tools.base import ToolError
from tools.image_intel import MAX_IMAGE_BYTES, fetch_image_bytes
from tools.net_guard import UnsafeURLError

router = APIRouter(tags=["geolocate"], dependencies=[Depends(verify_api_key)])


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"status": "error", "message": message})


@router.post("/api/geolocate")
@limiter.limit(heavy_limit)
async def geolocate_image(request: Request, response: Response,
                          file: UploadFile | None = File(None), url: str | None = Form(None)):
    try:
        if file is not None:
            data = await file.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                return _error(413, f"Image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
            if not data:
                return _error(400, "The uploaded file is empty.")
        elif url:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=False,
                                         headers={"User-Agent": "osint-tool/1.0"}) as client:
                data, _ct, _final = await fetch_image_bytes(client, normalize_image_url(url))
        else:
            return _error(400, "Upload an image file or give an image URL.")
        return await geolocate.analyze_upload(data)
    except (InvestigationValidationError, UnsafeURLError) as exc:
        return _error(400, str(exc))
    except ToolError as exc:
        return _error(502, str(exc))


class Place(BaseModel):
    name: str = Field(max_length=200)
    kind: str = "city"
    city: str | None = Field(None, max_length=120)
    country: str | None = Field(None, max_length=80)
    confidence: float = 0.5
    evidence: str | None = Field(None, max_length=300)


class RefineRequest(BaseModel):
    candidates: list[dict] = Field(default_factory=list, max_length=20)
    places: list[Place] = Field(default_factory=list, max_length=10)
    country_codes: list[str] = Field(default_factory=list, max_length=3)


@router.post("/api/geolocate/refine")
@limiter.limit(light_limit)
async def refine(request: Request, response: Response, payload: RefineRequest):
    try:
        return await geolocate.refine(payload.candidates, [p.model_dump() for p in payload.places],
                                      payload.country_codes)
    except ToolError as exc:
        return _error(502, str(exc))
