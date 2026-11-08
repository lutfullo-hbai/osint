import asyncio

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import store
from security import general_limit, limiter, verify_api_key
from services.correlate import correlate, nodes_from_findings

router = APIRouter(tags=["correlate"], dependencies=[Depends(verify_api_key)])


class CorrelateRequest(BaseModel):
    case_id: str | None = None
    nodes: list[dict] | None = None


@router.post("/api/correlate")
@limiter.limit(general_limit)
async def run_correlate(request: Request, response: Response, payload: CorrelateRequest):
    try:
        if payload.case_id:
            case = await asyncio.to_thread(store.get_case, payload.case_id)
            nodes = nodes_from_findings(case.get("findings", []))
        elif payload.nodes is not None:
            nodes = payload.nodes
        else:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Provide case_id or nodes."},
            )
        result = correlate(nodes)
        result["status"] = "success"
        return result
    except store.CaseError as exc:
        return JSONResponse(
            status_code=404, content={"status": "error", "message": str(exc)}
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Correlation failed: {exc}"},
        )
