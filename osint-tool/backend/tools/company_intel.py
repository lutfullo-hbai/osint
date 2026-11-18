"""Legal-entity intelligence via GLEIF (Global LEI Foundation).

GLEIF publishes the open Legal Entity Identifier register: official legal name,
address, registration status, local registration id and corporate parent links.
Free, no key, covers legal entities worldwide. This is company data, not people.
"""
import asyncio
import re
import time
from urllib.parse import quote

import httpx

from tools.base import NotConfigured, ToolError

GLEIF_BASE = "https://api.gleif.org/api/v1"
HEADERS = {
    "User-Agent": "osint-tool/1.0 (research)",
    "Accept": "application/vnd.api+json",
}
TIMEOUT = httpx.Timeout(20.0)
LEI_RE = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
MAX_MATCHES = 5
MAX_CHILDREN = 5


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
    try:
        response = await client.get(f"{GLEIF_BASE}{path}", **kwargs)
    except httpx.HTTPError as exc:
        # connection/timeout failures must surface as ToolError so the router
        # returns a clean 502, not an unhandled 500 echoing the raw error.
        raise ToolError(f"GLEIF is unreachable: {exc}") from exc
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


async def _children(client: httpx.AsyncClient, lei: str) -> tuple[list[dict], list[dict]]:
    """Direct subsidiaries that report this entity as their parent (GLEIF L2)."""
    data = await _get(client, f"/lei-records/{lei}/direct-children", params={"page[size]": MAX_CHILDREN})
    records = (data or {}).get("data") or []
    total = ((data or {}).get("meta") or {}).get("pagination", {}).get("total", len(records))
    results, pivots = [], []
    for record in records[:MAX_CHILDREN]:
        results.append(format_record(record, "Subsidiary (GLEIF)"))
        name = ((record.get("attributes") or {}).get("entity") or {}).get("legalName", {}).get("name")
        if name:
            pivots.append({"type": "company", "value": name})
    if total > len(records):
        results.append({
            "platform": "Subsidiaries (GLEIF)",
            "url": f"https://search.gleif.org/#/record/{lei}",
            "status": "found",
            "info": f"{total} direct subsidiaries report this parent; the first {len(records)} are shown.",
        })
    return results, pivots


async def companies_house_search(client: httpx.AsyncClient, query: str) -> list[dict]:
    """UK Companies House (free API key): company + its current officers."""
    import os

    key = os.environ.get("COMPANIES_HOUSE_API_KEY", "").strip()
    if not key:
        raise NotConfigured("COMPANIES_HOUSE_API_KEY not set")
    auth = httpx.BasicAuth(key, "")
    base = "https://api.company-information.service.gov.uk"
    response = await client.get(f"{base}/search/companies", params={"q": query, "items_per_page": 3}, auth=auth)
    if response.status_code == 401:
        raise ToolError("Companies House rejected the API key.")
    if response.status_code != 200:
        raise ToolError(f"Companies House returned HTTP {response.status_code}.")
    items = response.json().get("items") or []
    if not items:
        raise ToolError("No UK company matched.")
    results = []
    for index, item in enumerate(items[:3]):
        number = item.get("company_number", "")
        parts = [f"Organisation: {item.get('title', '')}", f"Company number: {number}",
                 f"Status: {item.get('company_status', '')}", f"Incorporated: {item.get('date_of_creation', '')}",
                 f"Address: {item.get('address_snippet', '')}"]
        if index == 0 and number:
            officers = await client.get(f"{base}/company/{number}/officers",
                                        params={"items_per_page": 10}, auth=auth)
            if officers.status_code == 200:
                active = [o for o in officers.json().get("items") or [] if not o.get("resigned_on")]
                if active:
                    parts.append("Officers: " + "; ".join(
                        f"{o.get('name')} ({o.get('officer_role')}, since {o.get('appointed_on', '?')})"
                        for o in active[:5]))
        results.append({
            "platform": "UK Companies House",
            "url": f"https://find-and-update.company-information.service.gov.uk/company/{number}",
            "status": "found",
            "info": "; ".join(p for p in parts if not p.endswith(": ")),
        })
    return results


async def sec_edgar_search(client: httpx.AsyncClient, query: str) -> dict:
    """Entities and filings mentioning this name in SEC EDGAR (mostly US public)."""
    response = await client.get(
        "https://efts.sec.gov/LATEST/search-index",
        params={"q": f'"{query}"'},
        headers={"User-Agent": "osint-tool/1.0 (OSINT research tool)"},
    )
    if response.status_code != 200:
        raise ToolError(f"SEC EDGAR returned HTTP {response.status_code}.")
    try:
        hits = response.json().get("hits", {}).get("hits", [])
    except ValueError as exc:
        raise ToolError("SEC EDGAR returned malformed JSON.") from exc
    if not hits:
        raise ToolError("No SEC filings mention this name.")

    entities: dict[str, dict] = {}
    for hit in hits:
        source = hit.get("_source", {})
        for name in source.get("display_names", []):
            entry = entities.setdefault(name, {"forms": set(), "latest": ""})
            for form in source.get("root_forms") or []:
                entry["forms"].add(form)
            date = source.get("file_date", "")
            if date > entry["latest"]:
                entry["latest"] = date

    lines = []
    for name, info in list(entities.items())[:4]:
        forms = ", ".join(sorted(info["forms"])[:5])
        lines.append(f"{name} [{forms}; latest {info['latest']}]")
    return {
        "platform": "SEC EDGAR",
        "url": f"https://efts.sec.gov/LATEST/search-index?q=%22{quote(query)}%22",
        "status": "found",
        "info": f"{len(hits)} filing(s) matched. " + " | ".join(lines),
    }


# GDELT allows one request per 5 seconds and answers slowly when busy: keep
# it from holding the whole company search hostage.
GDELT_TIMEOUT = httpx.Timeout(6.0, connect=4.0)
GDELT_INTERVAL_SECONDS = 5.0
GDELT_CACHE_TTL = 6 * 3600
_gdelt_lock = asyncio.Lock()
_gdelt_last = 0.0


async def gdelt_news(client: httpx.AsyncClient, query: str) -> dict:
    global _gdelt_last
    from cache import get_cached_json, set_cached_json

    key = f"osint:gdelt:{query.casefold()}"
    cached = await get_cached_json(key)
    if cached is not None:
        if cached.get("empty"):
            raise ToolError("No recent news mentions this name.")
        return cached
    async with _gdelt_lock:
        wait = _gdelt_last + GDELT_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            raise ToolError("GDELT skipped: its one-request-per-5-seconds limit was just used.")
        _gdelt_last = time.monotonic()
    try:
        response = await client.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": f'"{query}"',
                "format": "json",
                "maxrecords": 5,
                "sort": "datedesc",
                "timespan": "6months",
            },
            timeout=GDELT_TIMEOUT,
        )
    except httpx.TimeoutException as exc:
        raise ToolError("GDELT did not answer in time.") from exc
    if response.status_code == 429:
        raise ToolError("GDELT rate limit reached (one request / 5s).")
    content_type = response.headers.get("content-type", "")
    if response.status_code != 200 or "json" not in content_type:
        raise ToolError("GDELT did not return results.")
    try:
        articles = response.json().get("articles", []) or []
    except ValueError as exc:
        raise ToolError("GDELT returned malformed JSON.") from exc
    if not articles:
        await set_cached_json(key, {"empty": True}, GDELT_CACHE_TTL)
        raise ToolError("No recent news mentions this name.")
    lines = []
    for article in articles[:5]:
        date = str(article.get("seendate", ""))[:8]
        lines.append(f"{date} {article.get('domain', '')}: {article.get('title', '')[:70]}")
    result = {
        "platform": "News (GDELT)",
        "url": (
            "https://www.gdeltproject.org/"
        ),
        "status": "found",
        "info": " | ".join(lines),
    }
    await set_cached_json(key, result, GDELT_CACHE_TTL)
    return result


async def opencorporates_search(client: httpx.AsyncClient, query: str) -> dict:
    """Company registry search. Requires OPENCORPORATES_API_KEY."""
    import os

    token = os.environ.get("OPENCORPORATES_API_KEY", "").strip()
    if not token:
        raise NotConfigured("OPENCORPORATES_API_KEY not set")
    response = await client.get(
        "https://api.opencorporates.com/v0.4/companies/search",
        params={"q": query, "api_token": token, "per_page": 5},
    )
    if response.status_code == 401:
        raise ToolError("OpenCorporates rejected the API key.")
    if response.status_code != 200:
        raise ToolError(f"OpenCorporates returned HTTP {response.status_code}.")
    companies = (
        response.json().get("results", {}).get("companies", [])
    )
    if not companies:
        raise ToolError("No companies matched in OpenCorporates.")
    lines = []
    for item in companies[:5]:
        company = item.get("company", {})
        lines.append(
            f"{company.get('name')} ({company.get('jurisdiction_code')}, "
            f"{company.get('company_number')}, {company.get('current_status') or 'n/a'})"
        )
    return {
        "platform": "OpenCorporates",
        "url": f"https://opencorporates.com/companies?q={quote(query)}",
        "status": "found",
        "info": " | ".join(lines),
    }


async def _extra_sources(client: httpx.AsyncClient, query: str) -> tuple[list[dict], list[str]]:
    import asyncio as _asyncio

    sources = {
        "SEC EDGAR": sec_edgar_search(client, query),
        "News": gdelt_news(client, query),
        "OpenCorporates": opencorporates_search(client, query),
        "UK Companies House": companies_house_search(client, query),
    }
    outcomes = await _asyncio.gather(*sources.values(), return_exceptions=True)
    results = []
    warnings = []
    for label, outcome in zip(sources, outcomes):
        if isinstance(outcome, NotConfigured):
            continue
        if isinstance(outcome, ToolError):
            warnings.append(f"{label}: {outcome}")
        elif isinstance(outcome, BaseException):
            warnings.append(f"{label}: {type(outcome).__name__}")
        elif isinstance(outcome, list):
            results.extend(outcome)
        else:
            results.append(outcome)
    return results, warnings


async def run_company_search(query: str) -> dict:
    async with httpx.AsyncClient(
        headers=HEADERS, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        if LEI_RE.fullmatch(query.upper()):
            data = await _get(client, f"/lei-records/{query.upper()}")
            record = (data or {}).get("data")
            if not record:
                return {"results": [], "pivots": [], "warnings": []}
            results = [format_record(record)]
            (parent_results, pivots), (child_results, child_pivots) = await asyncio.gather(
                _parents(client, query.upper()), _children(client, query.upper()))
            results.extend(parent_results + child_results)
            return {"results": results, "pivots": pivots + child_pivots, "warnings": []}

        # GLEIF search and the extra sources run at the same time
        data, (extra_results, extra_warnings) = await asyncio.gather(
            _get(client, "/lei-records",
                 params={"filter[entity.legalName]": query, "page[size]": MAX_MATCHES}),
            _extra_sources(client, query),
        )
        records = (data or {}).get("data") or []
        if not records and not extra_results:
            return {"results": [], "pivots": [], "warnings": extra_warnings}

        results = [format_record(record) for record in records]
        pivots = []
        if records:
            lei = records[0]["attributes"]["lei"]
            (parent_results, pivots), (child_results, child_pivots) = await asyncio.gather(
                _parents(client, lei), _children(client, lei))
            results.extend(parent_results + child_results)
            pivots += child_pivots
        results.extend(extra_results)
        return {"results": results, "pivots": pivots, "warnings": extra_warnings}
