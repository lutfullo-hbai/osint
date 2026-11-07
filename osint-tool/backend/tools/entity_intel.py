"""Resolve a person's name to a Wikidata entity and Wikipedia summary.

Both are free, open APIs. Wikimedia blocks anonymous-looking clients, so every
request carries a descriptive User-Agent with a contact URL, per their robot
policy. Only notable people have entries; unknown names simply return nothing.
"""
import asyncio

import httpx

from tools.base import ToolError

WIKIMEDIA_HEADERS = {
    "User-Agent": (
        "osint-tool/1.0 (research; +https://github.com/lutfullo-hbai/osint)"
    ),
    "Accept": "application/json",
}
TIMEOUT = httpx.Timeout(15.0)
MAX_CANDIDATES = 2

# Wikidata property -> (label, pivot type). A handle on one of these becomes a
# pivot the investigator can click to search that platform next.
SOCIAL_PROPERTIES = {
    "P2037": ("GitHub", "username"),
    "P2002": ("X (Twitter)", "username"),
    "P2003": ("Instagram", "username"),
    "P7085": ("TikTok", "username"),
    "P2013": ("Facebook", None),
    "P4033": ("Mastodon", None),
    "P3789": ("Telegram", "username"),
    "P2397": ("YouTube channel", None),
}
BIRTH_PROPERTY = "P569"
DEATH_PROPERTY = "P570"
WEBSITE_PROPERTY = "P856"
OCCUPATION_PROPERTY = "P106"
CITIZENSHIP_PROPERTY = "P27"


async def _get_json(client: httpx.AsyncClient, url: str, **kwargs):
    response = await client.get(url, **kwargs)
    if response.status_code == 429:
        raise ToolError("Wikimedia rate limit reached.")
    if response.status_code != 200:
        raise ToolError(f"HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        raise ToolError("malformed JSON.") from exc


def _claim_value(claims: dict, prop: str):
    try:
        return claims[prop][0]["mainsnak"]["datavalue"]["value"]
    except (KeyError, IndexError, TypeError):
        return None


def _claim_ids(claims: dict, prop: str) -> list[str]:
    ids = []
    for claim in claims.get(prop, []):
        try:
            ids.append(claim["mainsnak"]["datavalue"]["value"]["id"])
        except (KeyError, TypeError):
            continue
    return ids


def _format_wikidata_time(value) -> str:
    if not isinstance(value, dict):
        return ""
    time_str = str(value.get("time", "")).lstrip("+")
    precision = value.get("precision", 11)
    date_part = time_str.split("T")[0]
    if precision <= 9:  # year only
        return date_part[:4]
    if precision == 10:  # year-month
        return date_part[:7]
    return date_part


async def _resolve_labels(client, qids: list[str]) -> dict[str, str]:
    if not qids:
        return {}
    data = await _get_json(
        client,
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbgetentities",
            "ids": "|".join(qids[:30]),
            "props": "labels",
            "languages": "en",
            "format": "json",
        },
    )
    labels = {}
    for qid, entity in (data.get("entities") or {}).items():
        label = ((entity.get("labels") or {}).get("en") or {}).get("value")
        if label:
            labels[qid] = label
    return labels


async def _wikipedia_summary(client, title: str) -> dict | None:
    data = await _get_json(
        client,
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}",
    )
    extract = (data.get("extract") or "").strip()
    if not extract:
        return None
    return {
        "platform": "Wikipedia",
        "url": (data.get("content_urls") or {}).get("desktop", {}).get("page", ""),
        "status": "found",
        "title": data.get("title") or title,
        "info": extract[:400],
    }


async def _entity_detail(client, qid: str, label: str, description: str) -> tuple[dict, list[dict]]:
    data = await _get_json(
        client, f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    )
    claims = (data.get("entities") or {}).get(qid, {}).get("claims") or {}

    occupation_ids = _claim_ids(claims, OCCUPATION_PROPERTY)
    country_ids = _claim_ids(claims, CITIZENSHIP_PROPERTY)
    labels = await _resolve_labels(client, occupation_ids + country_ids)

    fields = []
    if description:
        fields.append(description)
    birth = _format_wikidata_time(_claim_value(claims, BIRTH_PROPERTY))
    if birth:
        death = _format_wikidata_time(_claim_value(claims, DEATH_PROPERTY))
        fields.append(f"Born: {birth}" + (f"; Died: {death}" if death else ""))
    occupations = [labels[i] for i in occupation_ids if i in labels]
    if occupations:
        fields.append("Occupation: " + ", ".join(occupations[:5]))
    countries = [labels[i] for i in country_ids if i in labels]
    if countries:
        fields.append("Country: " + ", ".join(countries[:3]))

    pivots: list[dict] = []
    website = _claim_value(claims, WEBSITE_PROPERTY)
    social_notes = []
    for prop, (name, pivot_type) in SOCIAL_PROPERTIES.items():
        handle = _claim_value(claims, prop)
        if not handle or not isinstance(handle, str):
            continue
        social_notes.append(f"{name}: {handle}")
        if pivot_type == "username":
            pivots.append({"type": "username", "value": handle})
    if website:
        fields.append(f"Website: {website}")
    if social_notes:
        fields.append("Accounts: " + "; ".join(social_notes))

    entry = {
        "platform": "Wikidata",
        "url": f"https://www.wikidata.org/wiki/{qid}",
        "status": "found",
        "title": label,
        "info": "; ".join(fields) or "Entity found.",
    }
    return entry, pivots


async def run_person_entity(name: str) -> dict:
    async with httpx.AsyncClient(
        headers=WIKIMEDIA_HEADERS, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        search = await _get_json(
            client,
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": name,
                "language": "en",
                "uselang": "en",
                "type": "item",
                "limit": MAX_CANDIDATES,
                "format": "json",
            },
        )
        candidates = search.get("search") or []
        if not candidates:
            return {"results": [], "pivots": []}

        detail_tasks = [
            _entity_detail(
                client,
                candidate["id"],
                candidate.get("label") or name,
                candidate.get("description") or "",
            )
            for candidate in candidates
        ]
        summary_task = _wikipedia_summary(
            client, candidates[0].get("label") or name
        )
        outcomes = await asyncio.gather(
            *detail_tasks, summary_task, return_exceptions=True
        )

    results = []
    pivots = []
    *detail_outcomes, summary_outcome = outcomes
    for outcome in detail_outcomes:
        if isinstance(outcome, tuple):
            entry, entry_pivots = outcome
            results.append(entry)
            pivots.extend(entry_pivots)
    if isinstance(summary_outcome, dict):
        results.insert(0, summary_outcome)

    # Deduplicate pivots while preserving order.
    seen = set()
    unique_pivots = []
    for pivot in pivots:
        key = (pivot["type"], pivot["value"].casefold())
        if key not in seen:
            seen.add(key)
            unique_pivots.append(pivot)
    return {"results": results, "pivots": unique_pivots}


async def run_sanctions_check(name: str) -> dict:
    """Screen a name against OpenSanctions (sanctions / PEP lists).

    Requires OPENSANCTIONS_API_KEY; without it the check is skipped with a note,
    the same pattern as the HIBP breach check.
    """
    import os

    api_key = os.environ.get("OPENSANCTIONS_API_KEY", "").strip()
    if not api_key:
        return {
            "results": [],
            "warnings": [
                "Sanctions/PEP screening skipped: set OPENSANCTIONS_API_KEY to "
                "enable it (https://www.opensanctions.org/api/)."
            ],
        }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(
            "https://api.opensanctions.org/search/default",
            params={"q": name, "limit": 5},
            headers={"Authorization": f"ApiKey {api_key}", "Accept": "application/json"},
        )
    if response.status_code == 401:
        raise ToolError("OpenSanctions rejected the API key (HTTP 401).")
    if response.status_code != 200:
        raise ToolError(f"OpenSanctions returned HTTP {response.status_code}.")

    results = []
    for match in (response.json().get("results") or [])[:5]:
        properties = match.get("properties") or {}
        topics = properties.get("topics") or match.get("datasets") or []
        countries = properties.get("country") or []
        results.append(
            {
                "platform": "OpenSanctions",
                "url": f"https://www.opensanctions.org/entities/{match.get('id', '')}/",
                "status": "found",
                "title": match.get("caption") or name,
                "info": "; ".join(
                    part
                    for part in [
                        f"Type: {match.get('schema', '')}",
                        f"Lists: {', '.join(topics[:5])}" if topics else "",
                        f"Country: {', '.join(countries[:3])}" if countries else "",
                        "VERIFY: a name match is not proof of identity.",
                    ]
                    if part
                ),
            }
        )
    return {"results": results, "warnings": []}
