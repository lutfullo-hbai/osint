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

from services.investigate import (
    InvestigationValidationError,
    investigate_company,
    investigate_domain,
    investigate_email,
    investigate_name,
    investigate_phone,
    investigate_username,
)

# Bounds — keep a scan finite and friendly to upstream rate limits.
MAX_DEPTH = 2
MAX_NODES = 14
MAX_PIVOTS_PER_NODE = 6

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


async def run_deep_scan(seed_query: str, seed_type: str | None = None) -> dict:
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

    nodes: list[dict] = []
    edges: list[dict] = []
    seen: set[str] = set()
    warnings: list[str] = []
    truncated = False

    # queue holds (depth, ptype, value, parent_key_or_None)
    queue: list[tuple[int, str, str, str | None]] = [
        (0, seed_type, seed_query, None)
    ]
    seen.add(_node_key(seed_type, seed_query))

    while queue:
        if len(nodes) >= MAX_NODES:
            truncated = True
            break

        # process one depth level at a time, concurrently
        level = queue
        queue = []
        tasks = [
            _HANDLERS[ptype](value) for (_d, ptype, value, _p) in level
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for (depth, ptype, value, parent_key), result in zip(level, results):
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
            if result.get("message"):
                node["message"] = result["message"]
            nodes.append(node)

            if result.get("warnings"):
                warnings.extend(result["warnings"])

            if len(nodes) >= MAX_NODES:
                truncated = True
                break

            # enqueue children
            if depth + 1 <= MAX_DEPTH:
                for pivot in result.get("pivots", [])[:MAX_PIVOTS_PER_NODE]:
                    ctype = pivot.get("type")
                    cvalue = pivot.get("value")
                    if not ctype or not cvalue or ctype not in _HANDLERS:
                        continue
                    ckey = _node_key(ctype, cvalue)
                    if ckey in seen:
                        edges.append({"from": node_key, "to": ckey})
                        continue
                    seen.add(ckey)
                    queue.append((depth + 1, ctype, cvalue, node_key))

        if len(nodes) >= MAX_NODES:
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

    response = {
        "status": "success",
        "category": "deep_scan",
        "query": seed_query,
        "seed_type": seed_type,
        "nodes": nodes,
        "edges": uniq_edges,
        "node_count": len(nodes),
        "truncated": truncated,
        "notice": (
            "Deep Scan auto-follows public-source pivots from your seed. "
            "Matches across platforms are leads, not proof — a shared handle "
            "or name can belong to different people. Confirm before acting."
        ),
    }
    if warnings:
        response["warnings"] = warnings[:20]
    return response
