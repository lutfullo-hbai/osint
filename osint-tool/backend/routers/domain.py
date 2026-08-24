import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import httpx

from tools.base import ToolError
from tools.domain_intel import (
    DEFAULT_TIMEOUT,
    DomainValidationError,
    crtsh_lookup,
    dns_lookup,
    ip_geo_lookup,
    normalize_domain,
    rdap_lookup,
)

router = APIRouter(tags=["domain"])


class DomainRequest(BaseModel):
    query: str


@router.post("/api/domain")
async def search_domain(request: DomainRequest):
    try:
        domain = normalize_domain(request.query)
    except DomainValidationError as exc:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(exc)},
        )

    warnings: list[str] = []
    results: list[dict] = []

    async with httpx.AsyncClient(
        headers={"User-Agent": "osint-tool/1.0"},
        follow_redirects=True,
        timeout=DEFAULT_TIMEOUT,
    ) as client:
        rdap_outcome, crtsh_outcome, dns_outcome = await asyncio.gather(
            rdap_lookup(client, domain),
            crtsh_lookup(client, domain),
            dns_lookup(domain),
            return_exceptions=True,
        )
        if isinstance(rdap_outcome, BaseException):
            warnings.append(
                f"RDAP: {rdap_outcome}"
                if isinstance(rdap_outcome, ToolError)
                else f"RDAP failed unexpectedly: {type(rdap_outcome).__name__}"
            )
        else:
            results.append(rdap_outcome)

        if isinstance(crtsh_outcome, BaseException):
            warnings.append(
                f"crt.sh: {crtsh_outcome}"
                if isinstance(crtsh_outcome, ToolError)
                else f"crt.sh failed unexpectedly: {type(crtsh_outcome).__name__}"
            )
        else:
            results.append(crtsh_outcome)

        if isinstance(dns_outcome, BaseException):
            warnings.append(
                f"DNS: {dns_outcome}"
                if isinstance(dns_outcome, ToolError)
                else f"DNS failed unexpectedly: {type(dns_outcome).__name__}"
            )
        else:
            dns_entry, first_ip = dns_outcome
            results.append(dns_entry)
            if first_ip:
                try:
                    results.append(await ip_geo_lookup(client, first_ip))
                except ToolError as exc:
                    warnings.append(f"IP geolocation: {exc}")

    if not results:
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "message": "All lookups failed: " + "; ".join(warnings),
            },
        )

    response = {
        "status": "success",
        "category": "domain",
        "query": domain,
        "results": results,
        "count": len(results),
    }
    if warnings:
        response["warnings"] = warnings
    return response
