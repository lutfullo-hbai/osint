"""Identity correlation — turn a bag of OSINT nodes into identity clusters.

Given the nodes a Deep Scan (or a Case) produced, decide which ones plausibly
describe the SAME entity, score how strongly, and surface the corroborating
signals and any contradictions. This is reasoning over data we ALREADY have —
it opens no new source and crosses no red line. A shared handle or name is a
lead, never proof, so every cluster carries its evidence and its conflicts.
"""

from __future__ import annotations

import re
from collections import defaultdict

# Handles shorter than this collide too easily to be trusted as a link.
MIN_HANDLE_LEN = 4

# Link weights — how strongly a shared signal argues "same entity".
W_EMAIL = 3          # the same email address on two nodes
W_LINKED = 3         # a profile explicitly links out to another node's handle
W_AVATAR = 3         # the same perceptual avatar hash
W_HANDLE = 2         # the same username handle across nodes
W_LOCALPART = 2      # an email's local-part equals a username handle
W_NAME = 1           # the same full name (names collide — weak on its own)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_LOC_RE = re.compile(r"Location:\s*([^;]+)", re.IGNORECASE)
_NAME_RE = re.compile(r"Name:\s*([^;]+)", re.IGNORECASE)
_LINKED_RE = re.compile(r"Linked:\s*([^;]+)", re.IGNORECASE)
_DHASH_RE = re.compile(r"\bdhash[:=]?\s*([0-9a-f]{8,})", re.IGNORECASE)

# Known platforms whose profile URL ends in the user's handle.
_HANDLE_URL_RE = re.compile(
    r"https?://[^/]*(?:github\.com|gitlab\.com|twitter\.com|x\.com|instagram\.com|"
    r"t\.me|telegram\.me|reddit\.com/user|tiktok\.com/@|keybase\.io|"
    r"chess\.com/member|news\.ycombinator\.com/user|medium\.com/@|"
    r"gravatar\.com|about\.me|replit\.com/@)/?@?([A-Za-z0-9._\-]+)",
    re.IGNORECASE,
)


def norm_handle(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def norm_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())


def norm_email(value: str) -> str:
    return str(value).strip().lower()


def _extract(node: dict) -> dict:
    """Pull every identifier a node carries into normalized buckets."""
    ids = {
        "usernames": set(),
        "emails": set(),
        "names": set(),
        "domains": set(),
        "avatars": set(),
        "locations": set(),
        "platforms": set(),
    }
    ntype = node.get("type")
    query = str(node.get("query", "")).strip()

    if ntype == "username" and query:
        ids["usernames"].add(norm_handle(query))
    elif ntype == "email" and query:
        ids["emails"].add(norm_email(query))
        local = query.split("@", 1)[0]
        if len(norm_handle(local)) >= MIN_HANDLE_LEN:
            ids["usernames"].add(norm_handle(local))
    elif ntype == "name" and query:
        ids["names"].add(norm_name(query))
    elif ntype in ("domain", "ip") and query:
        ids["domains"].add(query.lower())

    for item in node.get("results", []) or []:
        platform = item.get("platform")
        if platform:
            ids["platforms"].add(platform)
        url = item.get("url") or item.get("profile_url") or ""
        m = _HANDLE_URL_RE.match(url)
        if m and len(norm_handle(m.group(1))) >= MIN_HANDLE_LEN:
            ids["usernames"].add(norm_handle(m.group(1)))

        linked = item.get("linked_username")
        if linked and len(norm_handle(linked)) >= MIN_HANDLE_LEN:
            ids["usernames"].add(norm_handle(linked))

        info = str(item.get("info", ""))
        for email in _EMAIL_RE.findall(info):
            ids["emails"].add(norm_email(email))
        for name in _NAME_RE.findall(info):
            if len(name.split()) >= 2:
                ids["names"].add(norm_name(name))
        for loc in _LOC_RE.findall(info):
            # keep original casing for display; contradictions compare lowercased
            ids["locations"].add(re.sub(r"\s+", " ", loc.strip()))
        for linked_group in _LINKED_RE.findall(info):
            # "gh:handle, tw:other" -> handle, other
            for token in re.split(r"[,\s]+", linked_group):
                handle = token.split(":")[-1]
                if len(norm_handle(handle)) >= MIN_HANDLE_LEN:
                    ids["usernames"].add(norm_handle(handle))
        for dh in _DHASH_RE.findall(info):
            ids["avatars"].add(dh.lower())
        name_field = item.get("name")
        if name_field and len(str(name_field).split()) >= 2:
            ids["names"].add(norm_name(name_field))

    return ids


def nodes_from_findings(findings: list[dict]) -> list[dict]:
    """Adapt stored case findings into the node shape correlate() expects.

    A deep-scan finding already holds its own nodes, so we expand those; every
    other finding becomes a single node carrying its result list.
    """
    nodes = []
    for finding in findings or []:
        category = finding.get("category")
        query = finding.get("query")
        result = finding.get("result") or {}
        if category == "deep_scan" and isinstance(result.get("nodes"), list):
            nodes.extend(result["nodes"])
            continue
        nodes.append({
            "key": f"{category}:{str(query).lower()}",
            "type": category,
            "query": query,
            "results": result.get("results", []),
        })
    return nodes


class _Union:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _confidence(score: int, members: int) -> str:
    if members < 2:
        return "single"
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def correlate(nodes: list[dict]) -> dict:
    """Cluster nodes that plausibly describe the same entity.

    Returns {"clusters": [...], "cluster_count": n}. Each cluster lists its
    member node keys, the identifiers that tie them, a confidence level, the
    human-readable signals behind it, and any contradictions (e.g. two
    different stated locations).
    """
    nodes = [n for n in nodes if isinstance(n, dict)]
    n = len(nodes)
    extracted = [_extract(node) for node in nodes]
    uf = _Union(n)

    # pairwise link scoring
    pair_score: dict[tuple[int, int], int] = defaultdict(int)
    pair_signals: dict[tuple[int, int], list[str]] = defaultdict(list)

    def link(i: int, j: int, weight: int, reason: str) -> None:
        key = (i, j) if i < j else (j, i)
        pair_score[key] += weight
        pair_signals[key].append(reason)
        uf.union(i, j)

    for i in range(n):
        for j in range(i + 1, n):
            ei, ej = extracted[i], extracted[j]
            shared_email = ei["emails"] & ej["emails"]
            if shared_email:
                link(i, j, W_EMAIL, f"shared email {sorted(shared_email)[0]}")
            shared_handle = ei["usernames"] & ej["usernames"]
            if shared_handle:
                link(i, j, W_HANDLE, f"shared handle @{sorted(shared_handle)[0]}")
            shared_avatar = ei["avatars"] & ej["avatars"]
            if shared_avatar:
                link(i, j, W_AVATAR, "identical avatar image hash")
            # email local-part of one == a handle of the other
            local_i = {e.split("@", 1)[0] for e in ei["emails"]}
            local_j = {e.split("@", 1)[0] for e in ej["emails"]}
            if ({norm_handle(x) for x in local_i} & ej["usernames"]) or (
                {norm_handle(x) for x in local_j} & ei["usernames"]
            ):
                link(i, j, W_LOCALPART, "email name reused as handle")
            shared_name = ei["names"] & ej["names"]
            if shared_name:
                link(i, j, W_NAME, f"shared name '{sorted(shared_name)[0]}'")

    # build clusters from union-find roots
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[uf.find(i)].append(i)

    clusters = []
    for members in groups.values():
        member_set = set(members)
        usernames: set[str] = set()
        emails: set[str] = set()
        names: set[str] = set()
        domains: set[str] = set()
        platforms: set[str] = set()
        locations: set[str] = set()
        for idx in members:
            e = extracted[idx]
            usernames |= e["usernames"]
            emails |= e["emails"]
            names |= e["names"]
            domains |= e["domains"]
            platforms |= e["platforms"]
            locations |= e["locations"]

        score = 0
        signals: list[str] = []
        for (a, b), s in pair_score.items():
            if a in member_set and b in member_set:
                score += s
                signals.extend(pair_signals[(a, b)])

        contradictions = []
        if len({loc.lower() for loc in locations}) > 1:
            contradictions.append(
                "different stated locations: " + "; ".join(sorted(locations))
            )

        label = (
            sorted(emails)[0] if emails
            else sorted(names)[0] if names
            else ("@" + sorted(usernames)[0]) if usernames
            else sorted(domains)[0] if domains
            else str(nodes[members[0]].get("query", "entity"))
        )

        clusters.append({
            "label": label,
            "members": [nodes[i].get("key") for i in members],
            "member_queries": [nodes[i].get("query") for i in members],
            "identifiers": {
                "usernames": sorted(usernames),
                "emails": sorted(emails),
                "names": sorted(names),
                "domains": sorted(domains),
            },
            "platforms": sorted(platforms),
            "score": score,
            "confidence": _confidence(score, len(members)),
            "signals": sorted(set(signals)),
            "contradictions": contradictions,
        })

    # most-connected clusters first, singletons last
    clusters.sort(key=lambda c: (len(c["members"]), c["score"]), reverse=True)
    return {"clusters": clusters, "cluster_count": len(clusters)}
