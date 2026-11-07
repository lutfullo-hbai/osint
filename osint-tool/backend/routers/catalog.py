from fastapi import APIRouter, Depends, Request, Response

from security import general_limit, limiter, verify_api_key
from tools.osint_catalog import get_catalog

router = APIRouter(tags=["catalog"], dependencies=[Depends(verify_api_key)])


@router.get("/api/catalog")
@limiter.limit(general_limit)
async def catalog(request: Request, response: Response):
    return get_catalog()
