"""Agent mode (ROADMAP Faza 6): free text in, sourced candidate profiles out.

    "lutfullo abdubaniyev 19 yosh namangandan"
      1. parse    -> name, age 19 (born ~2006-2007), place Namangan        (6.1)
      2. plan     -> name search + any identifiers the user gave + handles
                     guessed with the birth year                            (6.2)
      3. scan     -> one Deep Scan over all seeds; namesakes whose own data
                     contradicts the age/place are not expanded             (5.4)
      4. link     -> identity clusters (Faza 2) + the AI's cited 2nd opinion (Faza 5)
      5. rank     -> age and place agreement/contradiction move a candidate
                     up or down                                             (6.4)
      6. output   -> each candidate's fields with their source links, why it
                     was linked, what contradicts it, what was not found    (6.5)
The agent proposes; a person confirms or rejects every candidate          (6.6).
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any, Callable

from services.agent_parse import describe, has_target, parse_request
from services.correlate import (
    _BORN_RE,
    _EMAIL_RE,
    _LOC_RE,
    _NAME_RE,
    _extract,
    _from_search_only,
)
from services.deep_scan import _node_key, run_deep_scan
from services.investigate import InvestigationValidationError
from services.names import name_bits, name_tokens, names_match, places_conflict, username_variants

AGENT_MAX_NODES = 20
MAX_CANDIDATES = 8
MAX_FIELD_VALUES = 5
MAX_PROFILES = 12
YEAR_HANDLE_SEEDS = 2
CATCH_ALL_MIN_HANDLES = 3
CATCH_ALL_SHARE = 0.75

# Agent-level evidence (bits, same scale as correlate.py)
B_STATED = 6.0            # the user gave this identifier themselves
B_AGE_AGREE = 1.0
B_AGE_CONFLICT = -4.0
B_PLACE_AGREE = 1.0       # stronger than in correlate: the user named the town
B_PLACE_CONFLICT = -1.5
B_NAME_CONFLICT = -1.0
STRONG_LEAD = 6.0
POSSIBLE_LEAD = 3.0

FIELDS = ("name", "birth_year", "location", "emails", "usernames", "profiles")

NOTICE = (
    "Candidates are leads assembled from public sources, not identifications. "
    "Every field links to where it was seen. The agent never decides who a person is: "
    "confirm or reject each candidate yourself, and check the sources before acting."
)

_VIA_LABEL = {
    "knowledge_base": "listed on a knowledge base",
    "profile_link": "linked from a profile",
    "name_match": "same display name",
    "name_variant": "username guessed from the name",
    "email_localpart": "e-mail name used as a handle",
    "official_register": "official register",
    "stated": "you gave it",
}

Step = Callable[[str, str], Any]


# ---------------- target model ----------------

class Target:
    """What the user told us about the person, and how to compare to it."""

    def __init__(self, parsed: dict):
        self.parsed = parsed
        self.name = (parsed.get("names") or [None])[0]
        self.years = sorted(parsed.get("birth_years") or [])
        self.places = parsed.get("places") or []

    def age_check(self, births: set[int]) -> tuple[float, str] | None:
        if not births or not self.years:
            return None
        fitting = sorted(b for b in births if any(abs(b - y) <= 1 for y in self.years))
        if fitting:
            return B_AGE_AGREE, f"birth year {fitting[0]} fits the age you gave"
        return B_AGE_CONFLICT, (f"born {', '.join(map(str, sorted(births)))}, but the person you "
                                f"describe was born ~{self.years[-1]}")

    def place_check(self, locations: set[str]) -> tuple[float, str] | None:
        if not locations or not self.places:
            return None
        matching = sorted(loc for loc in locations if any(not places_conflict(loc, p) for p in self.places))
        if matching:
            return B_PLACE_AGREE, f"location '{matching[0]}' matches {', '.join(self.places)}"
        return B_PLACE_CONFLICT, (f"stated location '{'; '.join(sorted(locations))}', not "
                                  f"{', '.join(self.places)}")

    def name_check(self, names: set[str]) -> tuple[float, str] | None:
        if not names or not self.name:
            return None
        best, best_name = 0.0, None
        for name in names:
            common = names_match(self.name, name)
            if common and name_bits(common) > best:
                best, best_name = name_bits(common), name
        if best_name:
            return best, f"name '{best_name}' matches"
        if not any(name_tokens(self.name) & name_tokens(n) for n in names):
            return B_NAME_CONFLICT, f"different name: {', '.join(sorted(names)[:2])}"
        return None

    def expand(self, node: dict) -> tuple[bool, str]:
        """ROADMAP 5.4: is this node worth following further?

        A namesake whose own profile already contradicts the description
        (other birth year, other town, other name) would only spend the scan
        budget on someone else's accounts.
        """
        if node.get("depth", 0) == 0 or node.get("via") in ("knowledge_base", "profile_link", "stated"):
            return True, ""
        ids = _extract(node)
        for check in (self.age_check(ids["births"]), self.place_check(ids["locations"]),
                      self.name_check(ids["names"])):
            if check and check[0] < 0:
                return False, check[1]
        return True, ""


# ---------------- plan ----------------

def plan(parsed: dict) -> tuple[dict, list[dict]]:
    """Primary seed + extra seeds. Identifiers the user gave are 'stated'."""
    seeds = []
    for kind, ptype in (("names", "name"), ("emails", "email"), ("usernames", "username"),
                        ("phones", "phone"), ("domains", "domain")):
        seeds += [{"type": ptype, "value": v, "via": "stated"} for v in parsed.get(kind) or []]
    primary, extras = seeds[0], seeds[1:]
    name = (parsed.get("names") or [None])[0]
    if name and parsed.get("birth_years"):
        # people often add the birth year to a handle: lutfullo_abdubaniyev07
        parent = _node_key("name", name)
        guesses: list[str] = []
        for year in reversed(parsed["birth_years"]):
            guesses += [h for h in username_variants(name, birth_year=year, limit=10)
                        if re.search(r"\d", h) and h not in guesses][:1]
        extras += [{"type": "username", "value": h, "parent": parent, "via": "name_variant"}
                   for h in guesses[:YEAR_HANDLE_SEEDS]]
    return primary, extras


# ---------------- candidate building ----------------

# values people type into profile forms that say nothing ("Location: Location")
_PLACEHOLDERS = {"location", "name", "company", "none", "null", "n/a", "na", "-", "unknown",
                 "earth", "world", "internet", "planet earth", "everywhere", "somewhere", "here"}


def _add(field: dict, value: str, source: dict) -> None:
    value = " ".join(str(value).split()).strip(" ,;")[:160]
    if not value or value.casefold() in _PLACEHOLDERS:
        return
    key = value.casefold()
    entry = field.setdefault(key, {"value": value, "sources": []})
    if source and source not in entry["sources"] and len(entry["sources"]) < 4:
        entry["sources"].append(source)


def catch_all_platforms(nodes: list[dict]) -> set[str]:
    """Sites that "found" most of the different usernames checked in this run.

    Separate handles (guessed variants, namesakes) rarely all exist on the
    same small site; a site that says yes to nearly all of them is answering
    yes to anything. Complements the daily canary, which can miss a site that
    happened to time out during its check.
    """
    per_node = []
    for node in nodes:
        if node.get("type") == "username":
            per_node.append({str(i.get("platform") or "").casefold() for i in node.get("results") or []
                             if not _from_search_only(i)} - {""})
    if len(per_node) < CATCH_ALL_MIN_HANDLES:
        return set()
    counts: dict[str, int] = {}
    for platforms in per_node:
        for p in platforms:
            counts[p] = counts.get(p, 0) + 1
    return {p for p, n in counts.items() if n >= CATCH_ALL_MIN_HANDLES and n / len(per_node) >= CATCH_ALL_SHARE}


def profile_fields(members: list[dict], ignore_platforms: set[str] | None = None) -> dict:
    """Every field value with the pages it was seen on (6.5)."""
    ignore_platforms = ignore_platforms or set()
    raw = {f: {} for f in FIELDS}
    for node in members:
        ntype, query = node.get("type"), str(node.get("query") or "")
        searched = {"platform": f"{ntype} you searched" if node.get("via") == "stated" else f"{ntype} check",
                    "url": ""}
        if ntype == "email":
            _add(raw["emails"], query.lower(), searched)
        elif ntype == "username":
            _add(raw["usernames"], query, searched)
        for item in node.get("results") or []:
            if _from_search_only(item) or item.get("source") in ("dns_contact", "run_summary"):
                continue
            if str(item.get("status") or "found").lower() not in ("found", "success", "registered"):
                continue
            if str(item.get("platform") or "").casefold() in ignore_platforms:
                continue
            source = {"platform": str(item.get("platform") or "source")[:60], "url": item.get("url") or ""}
            info = str(item.get("info") or "")
            for name in _NAME_RE.findall(info) + ([item["name"]] if item.get("name") else []):
                if len(str(name).split()) >= 2:
                    _add(raw["name"], name, source)
            for loc in _LOC_RE.findall(info):
                _add(raw["location"], loc, source)
            for year in _BORN_RE.findall(info):
                _add(raw["birth_year"], year, source)
            for email in _EMAIL_RE.findall(info):
                _add(raw["emails"], email.lower(), source)
            if ntype in ("username", "email", "phone") and source["url"]:
                _add(raw["profiles"], source["platform"], source)
    fields = {}
    for field, values in raw.items():
        limit = MAX_PROFILES if field == "profiles" else MAX_FIELD_VALUES
        fields[field] = list(values.values())[:limit]
    return fields


def _candidate_id(member_keys: list[str]) -> str:
    return hashlib.sha256("|".join(sorted(member_keys)).encode()).hexdigest()[:12]


def _level(score: float, conflicts: list[str]) -> str:
    if conflicts and score < STRONG_LEAD:
        return "weak"
    if score >= STRONG_LEAD:
        return "strong"
    return "possible" if score >= POSSIBLE_LEAD else "weak"


def rank(scan: dict, target: Target, stated_keys: set[str]) -> tuple[list[dict], dict]:
    nodes = scan.get("nodes") or []
    by_key = {n["key"]: n for n in nodes}
    ai_by_key = {c.get("key"): c.get("ai_review") for cl in scan.get("clusters") or []
                 for c in cl.get("candidates") or [] if c.get("ai_review")}
    candidates, overview = [], {"name_search": []}
    ignored = catch_all_platforms(nodes)
    if ignored:
        overview["ignored_platforms"] = sorted(ignored)

    for cluster in scan.get("clusters") or []:
        members = [by_key[k] for k in cluster.get("members") or [] if k in by_key]
        if not members:
            continue
        types = {m.get("type") for m in members}
        # a name the user typed is the question, not evidence: only concrete
        # identifiers (username, e-mail, phone, domain) they gave count as stated
        stated = [m for m in members if m["key"] in stated_keys and m.get("type") != "name"]
        if not stated and not types & {"username", "email", "phone"}:
            # a name search on its own is an overview, not a person
            for m in members:
                if m.get("type") == "name":
                    overview["name_search"] += [
                        {"platform": i.get("platform"), "url": i.get("url"), "info": str(i.get("info") or "")[:200]}
                        for i in m.get("results") or [] if not _from_search_only(i)][:10]
            continue
        fields = profile_fields(members, ignored)
        if not stated and not any(fields[f] for f in FIELDS if f != "usernames"):
            continue                      # a guessed handle with no credible profile anywhere

        score = float(cluster.get("score") or 0.0)
        why = list(cluster.get("signals") or [])
        conflicts = list(cluster.get("contradictions") or [])
        if stated:
            score += B_STATED
            why.insert(0, "contains an identifier you gave: " + ", ".join(m["query"] for m in stated))
        births = {int(v["value"]) for v in fields["birth_year"] if str(v["value"]).isdigit()}
        locations = {v["value"] for v in fields["location"]}
        names = {v["value"] for v in fields["name"]}
        for check in (target.name_check(names), target.age_check(births), target.place_check(locations)):
            if check:
                score += check[0]
                (why if check[0] > 0 else conflicts).append(check[1])
        vias = {m.get("via") for m in members}
        if not stated and vias <= {"name_match", "name_variant", None} and len(members) == 1:
            why.append("found only through the name — may be a namesake")
        missing = [f for f in FIELDS if not fields[f]]
        label = (fields["name"][0]["value"] if fields["name"]
                 else ("@" + fields["usernames"][0]["value"]) if fields["usernames"]
                 else fields["emails"][0]["value"] if fields["emails"]
                 else str(cluster.get("label") or members[0].get("query")))
        candidate = {
            "id": _candidate_id([m["key"] for m in members]),
            "label": label,
            "score": round(score, 2),
            "level": _level(score, conflicts),
            "fields": fields,
            "missing": missing,
            "why": list(dict.fromkeys(why)),
            "contradictions": list(dict.fromkeys(conflicts)),
            "members": [{"key": m["key"], "type": m.get("type"), "query": m.get("query"),
                         "via": _VIA_LABEL.get(m.get("via"), m.get("via")), "count": m.get("count", 0),
                         "not_followed": m.get("not_followed")} for m in members],
        }
        reviews = [ai_by_key[m["key"]] for m in members if m["key"] in ai_by_key]
        if reviews:
            candidate["ai_review"] = reviews[0]
        candidates.append(candidate)

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:MAX_CANDIDATES], overview


# ---------------- run ----------------

async def run_agent(text: str, step: Step | None = None) -> dict:
    async def say(kind: str, message: str) -> None:
        if step is not None:
            outcome = step(kind, message)
            if asyncio.iscoroutine(outcome):
                await outcome

    parsed = parse_request(text)
    if not has_target(parsed):
        raise InvestigationValidationError(
            "Could not find a name, username, e-mail, phone or domain in the description.")
    await say("parse", "Understood: " + describe(parsed))
    target = Target(parsed)
    primary, extras = plan(parsed)
    stated_keys = {_node_key(s["type"], s["value"]) for s in [primary, *extras] if s.get("via") == "stated"}
    await say("plan", "Plan: " + "; ".join(
        f"{s['type']} '{s['value']}'" + (" (guessed)" if s.get("via") == "name_variant" else "")
        for s in [primary, *extras]) + " → follow pivots → link → rank by age and place")

    async def on_progress(event: dict) -> None:
        if event["kind"] == "node":
            via = _VIA_LABEL.get(event.get("via"), event.get("via"))
            await say("check", f"Checked {event['type']} '{event['query']}': {event['count']} result(s)"
                      + (f" — {via}" if via and event.get("depth") else ""))
        elif event["kind"] == "skip":
            await say("skip", f"Not following {event['type']} '{event['query']}': {event['reason']}")

    scan = await run_deep_scan(primary["value"], primary["type"], extra_seeds=extras,
                               progress=on_progress, expand=target.expand, max_nodes=AGENT_MAX_NODES)
    # the user's own identifiers are stated, not found by a pivot
    for node in scan["nodes"]:
        if node["key"] in stated_keys:
            node["via"] = "stated"
    await say("link", f"Linked {scan['node_count']} record(s) into {scan['cluster_count']} identity group(s)"
              + (f"; AI gave a second opinion on {scan['ai_reviewed']}" if scan.get("ai_reviewed") else ""))
    candidates, overview = rank(scan, target, stated_keys)
    strong = sum(c["level"] == "strong" for c in candidates)
    await say("rank", f"{len(candidates)} candidate(s), {strong} strong lead(s). Your decision is needed.")

    result = {
        "status": "success",
        "category": "agent",
        "query": parsed["text"],
        "parsed": parsed,
        "candidates": candidates,
        "overview": overview,
        "node_count": scan["node_count"],
        "truncated": scan["truncated"],
        "notice": NOTICE,
        "scan": {k: scan[k] for k in ("nodes", "edges", "clusters", "seed_type", "query")},
    }
    if scan.get("warnings"):
        result["warnings"] = scan["warnings"]
    return result


async def execute_run(run_id: str) -> dict:
    """Run a stored agent request, logging each step for the live view (6.3)."""
    import store  # local: keeps the service importable without the DB layer

    run = await asyncio.to_thread(store.get_agent_run, run_id)

    async def step(kind: str, message: str) -> None:
        await asyncio.to_thread(store.add_agent_step, run_id, kind, message)

    await asyncio.to_thread(store.update_agent_run, run_id, status="running")
    try:
        result = await run_agent(run["text"], step)
    except InvestigationValidationError as exc:
        await step("error", str(exc))
        await asyncio.to_thread(store.update_agent_run, run_id, status="failed", error=str(exc))
        return {"status": "failed", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - the run must end in a final state
        message = f"Agent failed: {type(exc).__name__}: {exc}"[:300]
        await step("error", message)
        await asyncio.to_thread(store.update_agent_run, run_id, status="failed", error=message)
        return {"status": "failed", "message": message}
    await asyncio.to_thread(store.update_agent_run, run_id, status="complete",
                            parsed=result["parsed"], result=result)
    return {"status": "complete"}
