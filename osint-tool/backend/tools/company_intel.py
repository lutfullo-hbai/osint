"""Legal-entity intelligence via GLEIF (Global LEI Foundation).

GLEIF publishes the open Legal Entity Identifier register: official legal name,
address, registration status, local registration id and corporate parent links.
Free, no key, covers legal entities worldwide. This is company data, not people.
"""
import asyncio
import re

import httpx

from tools.base import ToolError

GLEIF_BASE = "https://api.gleif.org/api/v1"
HEADERS = {
    "User-Agent": "osint-tool/1.0 (research)",
    "Accept": "application/vnd.api+json",
}
TIMEOUT = httpx.Timeout(20.0)
LEI_RE = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
MAX_MATCHES = 5


class CompanyValidationError(ValueError):
    pass


def normalize_company(raw: str) -> str:
    query = " ".join(raw.strip().split())
    if not (2 <= len(query) <= 140):
        raise CompanyValidationError(
            "Company name must be between 2 and 140 characters, or a 20-character LEI."
        )
    return query


def _address(block: dict) -> str:
    if not isinstance(block, dict):
        return ""
    parts = [
        *(block.get("addressLines") or []),
        block.get("city"),
        block.get("region"),
        block.get("postalCode"),
        block.get("country"),
    ]
    return ", ".join(str(p) for p in parts if p)


def format_record(record: dict, label: str = "Company (GLEIF)") -> dict:
    attributes = record.get("attributes") or {}
    lei = attributes.get("lei", "")
    entity = attributes.get("entity") or {}
    registration = attributes.get("registration") or {}
    name = (entity.get("legalName") or {}).get("name") or "Unknown"

    fields = [f"LEI: {lei}"]
    address = _address(entity.get("legalAddress"))
    if address:
        fields.append(f"Address: {address}")
    if entity.get("jurisdiction"):
        fields.append(f"Jurisdiction: {entity['jurisdiction']}")
    if entity.get("status"):
        fields.append(f"Entity status: {entity['status']}")
    legal_form = (entity.get("legalForm") or {}).get("id")
    if legal_form:
        fields.append(f"Legal form: {legal_form}")
    registered_as = entity.get("registeredAs")
    if registered_as:
        fields.append(f"Local reg. id: {registered_as}")
    if registration.get("status"):
        fields.append(f"LEI registration: {registration['status']}")
    last_update = (registration.get("lastUpdateDate") or "")[:10]
    if last_update:
        fields.append(f"Updated: {last_update}")

    return {
        "platform": label,
        "url": f"https://search.gleif.org/#/record/{lei}" if lei else "",
        "status": "found",
        "title": name,
        "info": "; ".join(fields),
    }


async def _get(client: httpx.AsyncClient, path: str, **kwargs):
    response = await client.get(f"{GLEIF_BASE}{path}", **kwargs)
    if response.status_code == 404:
        return None
    if response.status_code == 429:
        raise ToolError("GLEIF rate limit reached.")
    if response.status_code != 200:
        raise ToolError(f"GLEIF returned HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        raise ToolError("GLEIF returned malformed JSON.") from exc


async def _parents(client: httpx.AsyncClient, lei: str) -> tuple[list[dict], list[dict]]:
    results = []
    pivots = []
    for relation, label in (
        ("direct-parent", "Direct parent (GLEIF)"),
        ("ultimate-parent", "Ultimate parent (GLEIF)"),
    ):
        data = await _get(client, f"/lei-records/{lei}/{relation}")
        record = (data or {}).get("data")
        if not record:
            continue
        results.append(format_record(record, label))
        parent_name = (
            (record.get("attributes") or {}).get("entity") or {}
        ).get("legalName", {}).get("name")
        if parent_name:
            pivots.append({"type": "company", "value": parent_name})
    return results, pivots


async def run_company_search(query: str) -> dict:
    async with httpx.AsyncClient(
        headers=HEADERS, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        if LEI_RE.fullmatch(query.upper()):
            data = await _get(client, f"/lei-records/{query.upper()}")
            record = (data or {}).get("data")
            if not record:
                return {"results": [], "pivots": []}
            results = [format_record(record)]
            parent_results, pivots = await _parents(client, query.upper())
            results.extend(parent_results)
            return {"results": results, "pivots": pivots}

        data = await _get(
            client,
            "/lei-records",
            params={
                "filter[entity.legalName]": query,
                "page[size]": MAX_MATCHES,
            },
        )
        records = (data or {}).get("data") or []
        if not records:
            return {"results": [], "pivots": []}

        results = [format_record(record) for record in records]
        # Only resolve the parent chain for the single best match.
        parent_results, pivots = await _parents(
            client, records[0]["attributes"]["lei"]
        )
        results.extend(parent_results)
        return {"results": results, "pivots": pivots}
