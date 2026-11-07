import asyncio

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import store
from security import general_limit, limiter, verify_api_key

router = APIRouter(tags=["cases"], dependencies=[Depends(verify_api_key)])


class CaseCreate(BaseModel):
    name: str


class FindingCreate(BaseModel):
    category: str
    query: str
    result: dict


def _error(exc: store.CaseError, code: int = 400):
    return JSONResponse(status_code=code, content={"status": "error", "message": str(exc)})


@router.post("/api/cases")
@limiter.limit(general_limit)
async def create_case(request: Request, response: Response, payload: CaseCreate):
    try:
        return await asyncio.to_thread(store.create_case, payload.name)
    except store.CaseError as exc:
        return _error(exc)


@router.get("/api/cases")
@limiter.limit(general_limit)
async def list_cases(request: Request, response: Response):
    return {"cases": await asyncio.to_thread(store.list_cases)}


@router.get("/api/cases/{case_id}")
@limiter.limit(general_limit)
async def get_case(request: Request, response: Response, case_id: str):
    try:
        return await asyncio.to_thread(store.get_case, case_id)
    except store.CaseError as exc:
        return _error(exc, 404)


@router.post("/api/cases/{case_id}/findings")
@limiter.limit(general_limit)
async def add_finding(request: Request, response: Response, case_id: str, payload: FindingCreate):
    try:
        return await asyncio.to_thread(
            store.add_finding, case_id, payload.category, payload.query, payload.result
        )
    except store.CaseError as exc:
        return _error(exc, 404)


@router.delete("/api/cases/{case_id}")
@limiter.limit(general_limit)
async def delete_case(request: Request, response: Response, case_id: str):
    try:
        await asyncio.to_thread(store.delete_case, case_id)
        return {"status": "deleted"}
    except store.CaseError as exc:
        return _error(exc, 404)


@router.delete("/api/cases/{case_id}/findings/{finding_id}")
@limiter.limit(general_limit)
async def delete_finding(request: Request, response: Response, case_id: str, finding_id: str):
    try:
        await asyncio.to_thread(store.delete_finding, case_id, finding_id)
        return {"status": "deleted"}
    except store.CaseError as exc:
        return _error(exc, 404)
