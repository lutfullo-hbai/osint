import asyncio
import re

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import store
from security import heavy_limit, limiter, verify_api_key
from services.correlate import correlate, nodes_from_findings
from services.dossier import build_dossier

router = APIRouter(tags=["dossier"], dependencies=[Depends(verify_api_key)])


class DossierRequest(BaseModel):
    case_id: str | None = None
    data: dict | None = None


def _filename(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("_")[:60] or "report"
    return f"osint-dossier-{safe}.pdf"


@router.post("/api/dossier")
@limiter.limit(heavy_limit)
async def dossier(request: Request, response: Response, payload: DossierRequest):
    try:
        if payload.case_id:
            case = await asyncio.to_thread(store.get_case, payload.case_id)
            nodes = nodes_from_findings(case.get("findings", []))
            data = {
                "case_name": case.get("name"),
                "query": case.get("name"),
                "seed_type": "case",
                "nodes": nodes,
                "clusters": correlate(nodes)["clusters"],
            }
            name = case.get("name", "case")
        elif payload.data is not None:
            data = payload.data
            name = data.get("query", "report")
        else:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Provide case_id or data."},
            )
        pdf_bytes = await asyncio.to_thread(build_dossier, data)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{_filename(name)}"'},
        )
    except store.CaseError as exc:
        return JSONResponse(
            status_code=404, content={"status": "error", "message": str(exc)}
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Dossier build failed: {exc}"},
        )
