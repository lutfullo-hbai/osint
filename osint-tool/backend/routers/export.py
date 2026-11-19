"""Contact extraction from a page (ROADMAP 7.7) and graph export (7.8).

POST /api/contacts       {url}            contacts published on a page and its site
POST /api/export/graph   {scan, format}   Deep Scan graph as GraphML or Maltego CSV
"""
import re

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from security import general_limit, heavy_limit, limiter, verify_api_key
from services.graph_export import to_graphml, to_maltego_csv
from tools.contact_extract import extract_contacts
from tools.net_guard import UnsafeURLError, ensure_safe_url

router = APIRouter(tags=["export"], dependencies=[Depends(verify_api_key)])

MAX_EXPORT_NODES = 500
FORMATS = {
    "graphml": ("application/graphml+xml", "graphml", to_graphml),
    "maltego": ("text/csv; charset=utf-8", "csv", to_maltego_csv),
}


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"status": "error", "message": message})


def graph_file(scan: dict, fmt: str, name: str) -> Response:
    spec = FORMATS.get((fmt or "").lower())
    if spec is None:
        return _error(400, "format must be 'graphml' or 'maltego'.")
    if len(scan.get("nodes") or []) > MAX_EXPORT_NODES:
        return _error(400, f"At most {MAX_EXPORT_NODES} nodes per export.")
    media, ext, render = spec
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:60] or "graph"
    return Response(content=render(scan), media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{safe}.{ext}"'})


class ContactsRequest(BaseModel):
    url: str


class GraphRequest(BaseModel):
    scan: dict
    format: str = "graphml"


@router.post("/api/contacts")
@limiter.limit(heavy_limit)
async def contacts(request: Request, response: Response, payload: ContactsRequest):
    url = payload.url.strip()
    if not url or len(url) > 2000:
        return _error(400, "Give the page URL.")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    try:
        await ensure_safe_url(url)
    except UnsafeURLError as exc:
        return _error(400, str(exc))
    result = await extract_contacts(url)
    return {
        "status": "success",
        **result,
        "notice": ("Only what the pages themselves publish, each with the page it was read on. "
                   "robots.txt was obeyed; nothing was guessed."),
    }


@router.post("/api/export/graph")
@limiter.limit(general_limit)
async def export_graph(request: Request, response: Response, payload: GraphRequest):
    return graph_file(payload.scan, payload.format, f"deep-scan-{payload.scan.get('query') or 'graph'}")
