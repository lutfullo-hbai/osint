import os
import re

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tools.base import ToolError
from tools.holehe_runner import run_holehe

router = APIRouter(tags=["email"])

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

HTTP_HEADERS = {"User-Agent": "osint-tool/1.0 (local self-audit)"}


class EmailRequest(BaseModel):
    query: str


async def lookup_emailrep(email: str) -> dict:
    async with httpx.AsyncClient(headers=HTTP_HEADERS, timeout=20) as client:
        response = await client.get(f"https://emailrep.io/{email}")
    if response.status_code == 429:
        raise ToolError("EmailRep rate limit reached for this IP.")
    if response.status_code != 200:
        raise ToolError(f"EmailRep returned HTTP {response.status_code}.")
    data = response.json()

    info_parts = [f"Reputation: {data.get('reputation', 'unknown')}"]
    if "suspicious" in data:
        info_parts.append(f"Suspicious: {'yes' if data['suspicious'] else 'no'}")
    if "references" in data and data["references"] is not None:
        info_parts.append(f"References: {data['references']}")

    details = data.get("details") or {}
    if details.get("credentials_leaked"):
        info_parts.append("Credentials leaked: yes")
    if details.get("data_breach"):
        info_parts.append("Seen in data breaches: yes")
    if details.get("profiles"):
        profiles = details["profiles"]
        if profiles:
            info_parts.append(f"Public profiles on: {', '.join(profiles[:6])}")

    return {
        "platform": "EmailRep",
        "url": f"https://emailrep.io/{email}",
        "status": "found",
        "info": "; ".join(info_parts),
    }


async def lookup_hibp(email: str) -> tuple[dict | None, str | None]:
    api_key = os.environ.get("HIBP_API_KEY", "").strip()
    if not api_key:
        return None, (
            "HIBP breach check skipped: set the HIBP_API_KEY environment "
            "variable to enable it (https://haveibeenpwned.com/API/Key)."
        )
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.get(
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}"
            "?truncateResponse=false",
            headers={"hibp-api-key": api_key, **HTTP_HEADERS},
        )
    if response.status_code == 404:
        return {
            "platform": "HIBP Breaches",
            "url": "https://haveibeenpwned.com/",
            "status": "found",
            "info": "No known breaches contain this email. Good news.",
        }, None
    if response.status_code == 401:
        raise ToolError("HIBP rejected the API key (HTTP 401).")
    if response.status_code == 429:
        raise ToolError("HIBP rate limit reached. Retry later.")
    if response.status_code != 200:
        raise ToolError(f"HIBP returned HTTP {response.status_code}.")

    breaches = response.json()
    names = []
    for breach in breaches[:8]:
        name = breach.get("Name", "Unknown")
        date = breach.get("BreachDate", "")
        names.append(f"{name} ({date})" if date else name)
    more = len(breaches) - len(names)
    summary = ", ".join(names)
    if more > 0:
        summary += f" +{more} more"
    return {
        "platform": "HIBP Breaches",
        "url": "https://haveibeenpwned.com/",
        "status": "found",
        "info": f"Found in {len(breaches)} breach(es): {summary}",
    }, None


@router.post("/api/email")
async def search_email(request: EmailRequest):
    email = request.query.strip().lower()
    if not EMAIL_RE.fullmatch(email):
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "Please provide a valid email address.",
            },
        )

    warnings = []
    results = []

    try:
        holehe_outcome = await run_holehe(email)
        results.extend(holehe_outcome["results"])
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
                "message": f"Unexpected failure while running Holehe: {exc}",
            },
        )

    try:
        results.append(await lookup_emailrep(email))
    except ToolError as exc:
        warnings.append(f"EmailRep: {exc}")
    except Exception as exc:
        warnings.append(f"EmailRep failed unexpectedly: {type(exc).__name__}")

    try:
        hibp_entry, hibp_warning = await lookup_hibp(email)
        if hibp_entry:
            results.append(hibp_entry)
        if hibp_warning:
            warnings.append(hibp_warning)
    except ToolError as exc:
        warnings.append(f"HIBP: {exc}")
    except Exception as exc:
        warnings.append(f"HIBP failed unexpectedly: {type(exc).__name__}")

    response = {
        "status": "success",
        "query": email,
        "results": results,
        "count": len(results),
    }
    if warnings:
        response["warnings"] = warnings
    return response
