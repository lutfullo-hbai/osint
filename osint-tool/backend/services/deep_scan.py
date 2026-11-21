"""Deep Scan — automatic pivot-following orchestration.

Takes one seed (name / username / email / phone / domain / ip / company),
runs the matching investigator, then follows the pivots it returns to the
next investigators, breadth-first, up to a bounded depth and node count.

Only the existing public-source investigators are used; Deep Scan never
reaches a new data source. It just chains the ones we already have, so the
same red lines (no login-walled scraping, no leaks, no probiv) hold here too.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
from collections import defaultdict
from typing import Any, Callable

from services import ai
from services.correlate import correlate
from services.investigate import (
    InvestigationValidationError,
    investigate_company,
    investigate_domain,
    investigate_email,
    investigate_name,
    investigate_phone,
    investigate_username,
)

AI_REVIEW = os.environ.get("AI_REVIEW", "1").strip() not in ("0", "false", "no")

# Bounds — keep a scan finite and friendly to upstream rate limits.
MAX_DEPTH = 2
MAX_NODES = 14
MAX_PIVOTS_PER_NODE = 6
# Display-name matches are namesake candidates: follow only a few so they
# cannot crowd the node budget out.
MAX_NAME_MATCH_PIVOTS = 3
# Usernames guessed from a name (lutfullo.abdubaniyev): check only the top few.
MAX_NAME_VARIANT_PIVOTS = 2

# Pivot provenance ("via") -> follow order. Lower is followed first.
# "tagged" handles are people MENTIONED in a post, not the target: never
# followed automatically (they are still shown and clickable in the UI).
_VIA_PRIORITY = {
    "knowledge_base": 0,
    "age_confirmed": 0,     # 10.5b: namesake picked out by the age you gave (weaker than KB, see correlate)
    "profile_link": 1,
    None: 2,
    "email_localpart": 3,
    "name_match": 4,
    "name_variant": 5,
}
NOT_FOLLOWED_VIA = {"tagged"}


def _followable_pivots(pivots: list[dict]) -> list[dict]:
    """Strongest pivots first; drop mentions; cap namesake candidates."""
    keep = [p for p in pivots if p.get("via") not in NOT_FOLLOWED_VIA]
    keep.sort(key=lambda p: _VIA_PRIORITY.get(p.get("via"), 2))
    caps = {"name_match": MAX_NAME_MATCH_PIVOTS, "name_variant": MAX_NAME_VARIANT_PIVOTS}
    out, used = [], defaultdict(int)
    for pivot in keep:
        via = pivot.get("via")
        if via in caps:
            if used[via] >= caps[via]:
                continue
            used[via] += 1
        out.append(pivot)
    return out[:MAX_PIVOTS_PER_NODE]


def _node_pivots(result: dict) -> list[dict]:
    """A result's pivots plus its guessed usernames (weakest, followed last)."""
    pivots = list(result.get("pivots") or [])
    pivots += [
        {"type": "username", "value": handle, "via": "name_variant"}
        for handle in result.get("username_ideas") or []
    ]
    return pivots

# Heavy investigators (Sherlock + Maigret + profile APIs per username) run
# at most this many at once; a whole level fired together exhausted
# connections and made every source fail with ConnectError.
HEAVY_CONCURRENCY = {"username": 3, "name": 2}


def _limited(ptype: str, value: str, semaphores: dict):
    async def run():
        sem = semaphores.get(ptype)
        if sem is None:
            return await _HANDLERS[ptype](value)
        async with sem:
            return await _HANDLERS[ptype](value)
    return run()


# Pivot type -> investigator. "ip" shares the domain investigator, which
# routes IPs internally. "image" is intentionally excluded: it needs a URL
# and is not a profile pivot.
_HANDLERS = {
    "name": investigate_name,
    "username": investigate_username,
    "email": investigate_email,
    "phone": investigate_phone,
    "domain": investigate_domain,
    "ip": investigate_domain,
    "company": investigate_company,
}


def detect_type(query: str) -> str:
    """Best-effort guess of a seed's pivot type when none is given."""
    q = query.strip()
    if "@" in q and "." in q.split("@", 1)[-1]:
        return "email"
    digits = q.replace("+", "").replace("-", "").replace(" ", "")
    if q.startswith("+") or (digits.isdigit() and len(digits) >= 7):
        return "phone"
    # dotted token with no spaces -> domain or IP
    if " " not in q and "." in q and "@" not in q:
        return "domain"
    if " " not in q and q:
        return "username"
    return "name"


def _node_key(ptype: str, value: str) -> str:
    # IPs and domains live in one namespace so an IP found via a domain
    # (and vice versa) is not scanned twice.
    bucket = "host" if ptype in ("domain", "ip") else ptype
    return f"{bucket}:{value.strip().casefold()}"


async def _emit(progress: Callable[[dict], Any] | None, event: dict) -> None:
    """Report a step to the caller (Agent mode shows them live). Never fails the scan."""
    if progress is None:
        return
    try:
        outcome = progress(event)
        if inspect.isawaitable(outcome):
            await outcome
    except Exception:  # noqa: BLE001 - a broken progress sink must not stop the scan
        pass


# "GitHub: GitHub API rate limit reached." - a source that did not answer.
# Investigators report failures as "<Source>: <message>" or
# "<Source> failed unexpectedly: <Error>"; "45 site hit(s) ignored: ..." is not one.
_FAILED_SOURCE_RE = re.compile(
    r"^(?P<label>[A-Za-z][\w .\-]{1,40}?)(?: failed unexpectedly| skipped)?: (?P<msg>.*)$")
_FAILURE_WORDS = re.compile(
    r"rate limit|HTTP (?!404)\d{3}|unreachable|time(?:d)? ?out|Timeout|Error\b|malformed|"
    r"[A-Z][a-z]+Error|ConnectError|failed", re.IGNORECASE)


def unchecked_sources(result: dict) -> list[str]:
    """Sources that failed for this record: missing results there mean nothing."""
    names = {str(n) for n in result.get("failed_sources") or []}
    for warning in result.get("warnings") or []:
        match = _FAILED_SOURCE_RE.match(str(warning))
        if match and _FAILURE_WORDS.search(match.group("msg")) and not any(ch.isdigit() for ch in match.group("label")):
            names.add(match.group("label").strip())
    return sorted(names)


async def run_deep_scan(
    seed_query: str,
    seed_type: str | None = None,
    *,
    extra_seeds: list[dict] | None = None,
    progress: Callable[[dict], Any] | None = None,
    expand: Callable[[dict], tuple[bool, str]] | None = None,
    max_nodes: int | None = None,
    prepare: Callable[[list[dict]], Any] | None = None,
) -> dict:
    """Breadth-first pivot following.

    extra_seeds: more starting points, [{"type", "value", "parent"?, "via"?}]
        (Agent mode: an e-mail the user gave, a handle guessed with the birth year).
    progress: called with {"kind": "node" | "skip", ...} as each step finishes.
    expand(node) -> (follow, reason): whether a node's pivots are worth
        following (ROADMAP 5.4) — e.g. not a namesake born 30 years earlier.
    """
    node_budget = max_nodes or MAX_NODES
    seed_query = (seed_query or "").strip()
    if not seed_query:
        raise InvestigationValidationError("Deep Scan needs a query to start from.")

    seed_type = (seed_type or "").strip().lower() or detect_type(seed_query)
    if seed_type not in _HANDLERS:
        raise InvestigationValidationError(
            f"Deep Scan cannot start from a '{seed_type}' seed. Use one of: "
            + ", ".join(sorted(_HANDLERS))
            + "."
        )

    semaphores = {t: asyncio.Semaphore(n) for t, n in HEAVY_CONCURRENCY.items()}
    nodes: list[dict] = []
    edges: list[dict] = []
    seen: set[str] = set()
    warnings: list[str] = []
    truncated = False

    # queue holds (depth, ptype, value, parent_key_or_None, via_or_None)
    queue: list[tuple[int, str, str, str | None, str | None]] = [
        (0, seed_type, seed_query, None, None)
    ]
    seen.add(_node_key(seed_type, seed_query))
    for extra in extra_seeds or []:
        etype, evalue = extra.get("type"), str(extra.get("value") or "").strip()
        if etype not in _HANDLERS or not evalue or _node_key(etype, evalue) in seen:
            continue
        seen.add(_node_key(etype, evalue))
        queue.append((1 if extra.get("parent") else 0, etype, evalue, extra.get("parent"), extra.get("via")))

    while queue:
        if len(nodes) >= node_budget:
            truncated = True
            break

        # process one depth level at a time, concurrently
        level = queue
        queue = []
        tasks = [
            _limited(ptype, value, semaphores) for (_d, ptype, value, _p, _v) in level
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for (depth, ptype, value, parent_key, via), result in zip(level, results):
            node_key = _node_key(ptype, value)

            if isinstance(result, InvestigationValidationError):
                # a pivot value that this investigator rejects — skip quietly.
                # No node is created, so we add no edge to it (would dangle).
                continue
            if isinstance(result, BaseException):
                warnings.append(f"{ptype} '{value}': {result}")
                continue

            # the node exists — only now is it safe to link its parent to it
            if parent_key is not None:
                edges.append({"from": parent_key, "to": node_key})

            node = {
                "key": node_key,
                "type": ptype,
                "query": value,
                "depth": depth,
                "category": result.get("category", ptype),
                "status": result.get("status", "success"),
                "summary": result.get("summary"),
                "count": result.get("count", 0),
                "results": result.get("results", []),
                "pivots": result.get("pivots", []),
            }
            if parent_key is not None:
                # how this node was reached — correlation weighs it as evidence
                node["parent"] = parent_key
                node["via"] = via
            if result.get("message"):
                node["message"] = result["message"]
            unchecked = unchecked_sources(result)
            if unchecked:
                node["unchecked"] = unchecked              # 10.2: not "absent", just not asked
            if result.get("username_ideas"):
                node["username_ideas"] = list(result["username_ideas"])
            if prepare is not None:
                # Agent (10.1): set aside profiles that describe someone else NOW,
                # before this record's pivots are judged and followed
                try:
                    prepare([node])
                except Exception as exc:  # noqa: BLE001 - a filter bug must not stop the scan
                    warnings.append(f"profile check skipped for {ptype} '{value}': {type(exc).__name__}")
                for aside in node.get("set_aside") or []:
                    await _emit(progress, {"kind": "set_aside", "type": ptype, "query": value,
                                           "platform": aside.get("platform"), "reason": aside.get("reason")})
            nodes.append(node)

            if result.get("warnings"):
                warnings.extend(result["warnings"])
            await _emit(progress, {"kind": "node", "type": ptype, "query": value, "depth": depth,
                                   "count": node["count"], "via": via})

            if len(nodes) >= node_budget:
                truncated = True
                break

            # enqueue children — unless the caller judges this node not worth it
            follow = True
            if expand is not None and depth + 1 <= MAX_DEPTH and _node_pivots(node):
                follow, reason = expand(node)
                if not follow:
                    node["not_followed"] = reason
                    await _emit(progress, {"kind": "skip", "type": ptype, "query": value, "reason": reason})
            if follow and depth + 1 <= MAX_DEPTH:
                for pivot in _followable_pivots(_node_pivots(node)):
                    ctype = pivot.get("type")
                    cvalue = pivot.get("value")
                    if not ctype or not cvalue or ctype not in _HANDLERS:
                        continue
                    ckey = _node_key(ctype, cvalue)
                    if ckey in seen:
                        edges.append({"from": node_key, "to": ckey})
                        continue
                    seen.add(ckey)
                    queue.append(
                        (depth + 1, ctype, cvalue, node_key, pivot.get("via"))
                    )

        if len(nodes) >= node_budget:
            truncated = True
            break

    # dedupe edges and drop any whose endpoints are not both real nodes.
    # Cross-link edges (to an already-seen pivot) can dangle if that node was
    # never scanned because MAX_NODES was reached first — filter those out so
    # the graph the client receives is always internally consistent.
    node_keys = {n["key"] for n in nodes}
    uniq_edges = []
    edge_seen = set()
    for e in edges:
        if e["from"] not in node_keys or e["to"] not in node_keys:
            continue
        ek = (e["from"], e["to"])
        if ek not in edge_seen:
            edge_seen.add(ek)
            uniq_edges.append(e)

    correlation = correlate(nodes)
    # a weak, cited second opinion on unmerged candidates (never merges)
    reviewed = 0
    if AI_REVIEW:
        try:
            reviewed = await ai.review_clusters(nodes, correlation["clusters"])
        except Exception:  # noqa: BLE001 - AI is optional
            reviewed = 0

    response = {
        "status": "success",
        "category": "deep_scan",
        "query": seed_query,
        "seed_type": seed_type,
        "nodes": nodes,
        "edges": uniq_edges,
        "node_count": len(nodes),
        "clusters": correlation["clusters"],
        "cluster_count": correlation["cluster_count"],
        "truncated": truncated,
        "ai_reviewed": reviewed,
        "notice": (
            "Deep Scan auto-follows public-source pivots from your seed. "
            "Matches across platforms are leads, not proof — a shared handle "
            "or name can belong to different people. Confirm before acting."
        ),
    }
    if warnings:
        response["warnings"] = warnings[:20]
    return response
