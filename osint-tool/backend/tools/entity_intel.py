"""Resolve a person's name to a Wikidata entity and Wikipedia summary.

Both are free, open APIs. Wikimedia blocks anonymous-looking clients, so every
request carries a descriptive User-Agent with a contact URL, per their robot
policy. Only notable people have entries; unknown names simply return nothing.
"""
import asyncio
import re
import unicodedata

import httpx

from tools.base import ToolError

WIKIMEDIA_HEADERS = {
    "User-Agent": (
        "osint-tool/1.0 (research; +https://github.com/lutfullo-hbai/osint)"
    ),
    "Accept": "application/json",
}
TIMEOUT = httpx.Timeout(15.0)
MAX_CANDIDATES = 2          # entities fetched in full (detail + accounts)
GRADING_CANDIDATES = 8      # entities checked for "another human with this exact name"
INSTANCE_OF_PROPERTY = "P31"
HUMAN_QID = "Q5"

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


def _birth_year(claims: dict) -> int | None:
    """Year of birth from a P569 claim ("+1987-00-00T00:00:00Z" -> 1987)."""
    value = _claim_value(claims, BIRTH_PROPERTY)
    match = re.match(r"\+?(\d{4})-", str(value.get("time", ""))) if isinstance(value, dict) else None
    return int(match.group(1)) if match else None


_BORN_RE = re.compile(r"\bBorn: (\d{4})\b")


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


def _norm_label(value: str) -> str:
    """Casefold, strip accents and apostrophe variants, collapse spaces."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[\'\u2018\u2019\u02bb\u02bc`]", "", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


async def _entity_detail(client, qid: str, label: str, description: str) -> tuple[dict, list[dict], bool]:
    data = await _get_json(
        client, f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    )
    claims = (data.get("entities") or {}).get(qid, {}).get("claims") or {}
    is_human = HUMAN_QID in _claim_ids(claims, INSTANCE_OF_PROPERTY)

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
            # the caller decides how much this is worth (see run_person_entity)
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
    return entry, pivots, is_human


def _grade_pivots(name: str, details: list[tuple[dict, list[dict], bool]],
                  other_matching_humans: int = 0, other_births: tuple = ()) -> list[dict]:
    """Decide how strongly each entity's accounts identify the searched person.

    A Wikidata search returns every item that shares the name. Only a human
    whose label equals the query AND who is the ONLY such human is treated as
    "the" person: their accounts are knowledge-base evidence. When two humans
    share the name (Michael Jordan the player and the professor) nobody knows
    which one is meant, so every account is a namesake candidate. Non-human
    items (a film, a band) contribute nothing.

    10.5b: a namesake candidate of an exactly matching human carries that
    human's birth year ("born") and the birth years of the other humans with
    this name ("namesake_births", None = not recorded), so a caller that knows
    the person's age can tell them apart (agent.Target.confirm_by_age).
    """
    wanted = _norm_label(name)
    matching = [
        d for d in details if d[2] and _norm_label(d[0].get("title")) == wanted
    ]
    # a namesake further down the search (not fetched in full) also counts
    unique = matching[0] if len(matching) == 1 and other_matching_humans == 0 else None
    def born(detail) -> int | None:
        match = _BORN_RE.search(str(detail[0].get("info") or ""))
        return int(match.group(1)) if match else None

    graded = []
    for detail in details:
        entry, pivots, is_human = detail
        if not is_human:
            continue
        if detail is unique:
            graded.extend({**p, "via": "knowledge_base"} for p in pivots)
            continue
        extra = {}
        if any(d is detail for d in matching):
            others = [born(d) for d in matching if d is not detail] + list(other_births)
            # namesakes further down the search whose birth year was not read are unknown
            others += [None] * max(0, other_matching_humans - len(other_births))
            extra = {"born": born(detail), "namesake_births": others}
        graded.extend({**p, "via": "name_match", **extra} for p in pivots)
    return graded


async def _matching_humans(client, name: str, qids: list[str]) -> list[int | None]:
    """Birth years (None = not recorded) of the items that are humans labelled
    exactly like the query: one entry per such human."""
    if not qids:
        return []
    try:
        data = await _get_json(client, "https://www.wikidata.org/w/api.php", params={
            "action": "wbgetentities", "ids": "|".join(qids), "props": "labels|claims",
            "languages": "en", "format": "json"})
    except ToolError:
        return [None]  # unknown: be conservative, do not call anyone "unique"
    wanted = _norm_label(name)
    births = []
    for entity in (data.get("entities") or {}).values():
        label = ((entity.get("labels") or {}).get("en") or {}).get("value", "")
        claims = entity.get("claims") or {}
        if HUMAN_QID in _claim_ids(claims, INSTANCE_OF_PROPERTY) and _norm_label(label) == wanted:
            births.append(_birth_year(claims))
    return births


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
                "limit": GRADING_CANDIDATES,
                "format": "json",
            },
        )
        found = search.get("search") or []
        if not found:
            return {"results": [], "pivots": []}
        candidates = found[:MAX_CANDIDATES]
        other_births = await _matching_humans(client, name, [c["id"] for c in found[MAX_CANDIDATES:]])

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
    *detail_outcomes, summary_outcome = outcomes
    details = [o for o in detail_outcomes if isinstance(o, tuple)]
    results.extend(entry for entry, _p, _h in details)
    pivots = _grade_pivots(name, details, len(other_births), tuple(other_births))
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


async def run_sanctions_check(name: str, birth_year: int | None = None) -> dict:
    """Screen a name against sanctions and PEP lists.

    Free by default: our local index of the official UN, OFAC, EU and UK lists
    plus Wikidata PEPs (tools/sanctions_index.py, refreshed by the worker).
    The paid OpenSanctions API is used only if OPENSANCTIONS_API_KEY is set.
    """
    import os

    from tools import sanctions_index

    api_key = os.environ.get("OPENSANCTIONS_API_KEY", "").strip()
    try:
        local = await asyncio.to_thread(sanctions_index.search, name, birth_year)
    except ToolError:
        if not api_key:
            raise          # surfaces as a warning + short cache, never as "clean"
        local = []
    local_results = [sanctions_index.to_result(hit) for hit in local]
    if not api_key:
        return {"results": local_results, "warnings": []}

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
    return {"results": local_results + results, "warnings": []}
