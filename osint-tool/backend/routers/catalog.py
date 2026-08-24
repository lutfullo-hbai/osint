from fastapi import APIRouter

from tools.osint_catalog import get_catalog

router = APIRouter(tags=["catalog"])


@router.get("/api/catalog")
async def catalog():
    return get_catalog()
