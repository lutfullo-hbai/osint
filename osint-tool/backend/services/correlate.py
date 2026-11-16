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
from urllib.parse import parse_qs, urlparse

# Handles shorter than this collide too easily to be trusted as a link.
MIN_HANDLE_LEN = 4

# Link weights — how strongly a shared signal argues "same entity".
W_KB = 5             # a curated knowledge base (Wikidata) lists the account
W_STATED_EMAIL = 5   # a profile itself publishes the email being investigated
W_EMAIL = 3          # the same email address on two nodes
W_LINKED = 3         # a profile explicitly links out to another node's handle
W_AVATAR = 3         # the same perceptual avatar hash
W_HANDLE = 2         # the same username handle across nodes
W_LOCALPART = 2      # an email's local-part equals a username handle
W_NAME = 1           # the same full name (names collide — weak on its own)

# A generic handle links nothing: common words collide across unrelated people.
# Two defences: a stoplist of dictionary/role handles, and a frequency cap —
# a handle registered on an implausible number of platforms is a common word,
# not a person's identity. Both only suppress the handle LINK; the individual
# nodes still appear, just not glued into one cluster.
STOPLIST_HANDLES = {
    "hello", "admin", "info", "test", "tests", "user", "users", "contact",
    "support", "mail", "email", "root", "account", "accounts", "official",
    "team", "news", "home", "login", "signup", "help", "service", "services",
    "welcome", "default", "guest", "demo", "sample", "example", "public",
    "private", "social", "socials", "me", "null", "none", "name", "username",
    "password", "anonymous", "unknown", "nobody", "everyone", "staff", "sales",
    "office", "online", "world", "global", "main", "web", "app", "site",
    # URL path words a profile-URL pattern can mistake for a handle
    "popular", "explore", "trending", "hashtag", "search", "share", "watch",
    "status", "intent", "discover", "about", "people", "profile", "settings",
}
GENERIC_PLATFORM_THRESHOLD = 18  # a handle seen on >= this many platforms is generic

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_LOC_RE = re.compile(r"Location:\s*([^;]+)", re.IGNORECASE)
_NAME_RE = re.compile(r"Name:\s*([^;]+)", re.IGNORECASE)
_LINKED_RE = re.compile(r"Linked:\s*([^;]+)", re.IGNORECASE)
_DHASH_RE = re.compile(r"\bdhash[:=]?\s*([0-9a-f]{8,})", re.IGNORECASE)

# Known platforms whose profile URL carries the user's handle.
# host -> (path prefix before the handle, reserved first segments that are
# site pages, not users). The host must match EXACTLY (after www./m.), so
# budget.me is not t.me and netflix.com/title/1 is not x.com/title.
_PROFILE_HOSTS: dict[str, tuple[str, frozenset]] = {
    "github.com": ("", frozenset({
        "topics", "orgs", "sponsors", "features", "settings", "marketplace",
        "explore", "about", "login", "join", "pricing", "enterprise",
        "collections", "trending", "apps", "search", "notifications",
        "issues", "pulls", "site", "security", "readme", "events", "new",
        "organizations", "codespaces", "customer-stories", "team", "contact",
    })),
    "gitlab.com": ("", frozenset({"explore", "users", "help", "groups", "projects", "dashboard"})),
    "twitter.com": ("", frozenset({"i", "home", "intent", "search", "hashtag", "explore", "share", "settings", "messages"})),
    "x.com": ("", frozenset({"i", "home", "intent", "search", "hashtag", "explore", "share", "settings", "messages"})),
    "instagram.com": ("", frozenset({"p", "reel", "reels", "explore", "stories", "accounts", "tv", "direct"})),
    "t.me": ("", frozenset({"s", "c", "joinchat", "share", "addstickers", "addemoji", "proxy", "iv"})),
    "telegram.me": ("", frozenset({"s", "c", "joinchat", "share", "addstickers", "addemoji", "proxy", "iv"})),
    "reddit.com": ("user/", frozenset()),
    "tiktok.com": ("@", frozenset()),
    "keybase.io": ("", frozenset({"docs", "blog", "download", "jobs"})),
    "chess.com": ("member/", frozenset()),
    "medium.com": ("@", frozenset()),
    "gravatar.com": ("", frozenset({"avatar", "site", "support", "connect", "profile"})),
    "about.me": ("", frozenset({"login", "signup", "people", "search"})),
    "replit.com": ("@", frozenset()),
}
_HANDLE_CHARS_RE = re.compile(r"^[A-Za-z0-9._\-]+$")


def handle_from_url(url: str) -> str | None:
    """The username a known profile URL points at, or None."""
    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    for prefix in ("www.", "m.", "mobile.", "old."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    if host == "news.ycombinator.com":
        if parsed.path.rstrip("/") != "/user":
            return None
        value = (parse_qs(parsed.query).get("id") or [""])[0]
        return value if _HANDLE_CHARS_RE.match(value) else None
    rule = _PROFILE_HOSTS.get(host)
    if rule is None:
        return None
    prefix, reserved = rule
    path = parsed.path.lstrip("/")
    if host == "reddit.com" and path.startswith("u/"):
        path = "user/" + path[2:]
    if not path.lower().startswith(prefix):
        return None
    segment = path[len(prefix):].split("/", 1)[0]
    if not prefix and segment.startswith("@"):
        segment = segment[1:]
    if not segment or segment.lower() in reserved or not _HANDLE_CHARS_RE.match(segment):
        return None
    return segment


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
        # email local-parts: matched against handles once, never as handles
        "localparts": set(),
        # handles a NAME search surfaced (display-name matches): namesake
        # candidates, never identity evidence on their own
        "candidate_handles": set(),
        # handle -> platforms it was seen on, to spot generic (over-common) ones
        "handle_platforms": defaultdict(set),
    }
    ntype = node.get("type")
    query = str(node.get("query", "")).strip()

    if ntype == "username" and query:
        ids["usernames"].add(norm_handle(query))
    elif ntype == "email" and query:
        ids["emails"].add(norm_email(query))
    elif ntype == "name" and query:
        ids["names"].add(norm_name(query))
    elif ntype in ("domain", "ip") and query:
        ids["domains"].add(query.lower())

    for item in node.get("results", []) or []:
        platform = item.get("platform")
        if platform:
            ids["platforms"].add(platform)
        # a web-search hit is a page that MENTIONS the query: the accounts and
        # addresses on it are usually other people's, so they are not this
        # node's identifiers (a name search still uses them as candidates)
        from_search = item.get("source") == "web_search"
        url = item.get("url") or item.get("profile_url") or ""
        raw_handle = handle_from_url(url)
        if raw_handle and len(norm_handle(raw_handle)) >= MIN_HANDLE_LEN:
            h = norm_handle(raw_handle)
            if from_search and ntype != "name" and h != norm_handle(query):
                continue
            # a name search returns everyone who shares the name, so a handle
            # in its results is a candidate, not the searched person's handle
            bucket = "candidate_handles" if ntype == "name" else "usernames"
            ids[bucket].add(h)
            if platform:
                ids["handle_platforms"][h].add(platform)

        linked = item.get("linked_username")
        if linked and len(norm_handle(linked)) >= MIN_HANDLE_LEN:
            ids["usernames"].add(norm_handle(linked))

        if from_search:
            continue
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

    ids["localparts"] = {
        norm_handle(e.split("@", 1)[0]) for e in ids["emails"]
    } - {""}
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
            # keep provenance: without it every pivot reads as unknown evidence
            "pivots": result.get("pivots", []),
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


def _confidence(strength: int, members: int) -> str:
    if members < 2:
        return "single"
    if strength >= 5:
        return "high"
    if strength >= 3:
        return "medium"
    return "low"


def _node_ref(ptype: str, value: str) -> tuple[str, str]:
    if ptype == "username":
        return ("username", norm_handle(value))
    if ptype == "email":
        return ("email", norm_email(value))
    if ptype in ("domain", "ip"):
        return ("host", str(value).strip().lower())
    return (str(ptype), norm_name(value))


def correlate(nodes: list[dict]) -> dict:
    """Cluster nodes that plausibly describe the same entity.

    Returns {"clusters": [...], "cluster_count": n}. Each cluster lists its
    member node keys, the identifiers that tie them, a confidence level, the
    human-readable signals behind it, any contradictions (e.g. two different
    stated locations) and namesake candidates that were NOT merged.

    Evidence rules:
    - a pivot is not evidence of itself: when node B was reached from node A,
      the handle that was followed does not also count as a "shared handle";
    - how a pivot was found decides its weight ("via"): a knowledge-base
      listing or a profile linking out is evidence; a display-name match is
      only a candidate; a tagged @mention is nothing;
    - confidence is set by the cluster's WEAKEST member, so many weak links
      can never add up to "high".
    """
    nodes = [n for n in nodes if isinstance(n, dict)]
    n = len(nodes)
    extracted = [_extract(node) for node in nodes]
    refs = [_node_ref(node.get("type"), node.get("query", "")) for node in nodes]
    uf = _Union(n)

    # node -> {ref of a pivot it produced: via}
    pivot_via: list[dict] = []
    for node in nodes:
        vias = {}
        for pivot in node.get("pivots") or []:
            if isinstance(pivot, dict) and pivot.get("type") and pivot.get("value"):
                ref = _node_ref(pivot["type"], pivot["value"])
                vias.setdefault(ref, pivot.get("via"))
        pivot_via.append(vias)

    # global handle frequency across all nodes -> spot over-common handles
    handle_freq: dict[str, set] = defaultdict(set)
    for e in extracted:
        for handle, platforms in e["handle_platforms"].items():
            handle_freq[handle] |= platforms

    def is_generic(handle: str) -> bool:
        return (
            handle in STOPLIST_HANDLES
            or len(handle_freq.get(handle, ())) >= GENERIC_PLATFORM_THRESHOLD
        )

    # pairwise link scoring
    pair_score: dict[tuple[int, int], int] = defaultdict(int)
    pair_signals: dict[tuple[int, int], list[str]] = defaultdict(list)
    # hub index -> [(candidate index, reason)] — shown, never merged
    candidates: dict[int, list[tuple[int, str]]] = defaultdict(list)

    def link(i: int, j: int, weight: int, reason: str) -> None:
        key = (i, j) if i < j else (j, i)
        pair_score[key] += weight
        pair_signals[key].append(reason)
        uf.union(i, j)

    def candidate(hub: int, other: int, reason: str) -> None:
        if all(c != other for c, _ in candidates[hub]):
            candidates[hub].append((other, reason))

    for i in range(n):
        for j in range(i + 1, n):
            ei, ej = extracted[i], extracted[j]

            # how one node led to the other, if it did
            via, parent, child = None, None, None
            if refs[j] in pivot_via[i]:
                via, parent, child = pivot_via[i][refs[j]], i, j
            elif refs[i] in pivot_via[j]:
                via, parent, child = pivot_via[j][refs[i]], j, i
            # the followed handle itself is not independent evidence
            followed = {refs[child][1]} if child is not None and refs[child][0] == "username" else set()

            if via == "knowledge_base":
                link(i, j, W_KB, f"listed on a knowledge base: @{refs[child][1]}")
            elif via == "profile_link":
                link(i, j, W_LINKED, f"profile links to {refs[child][1]}")
            elif via == "name_match":
                candidate(parent, child,
                          "display name matches — may be a different person")

            shared_email = ei["emails"] & ej["emails"]
            if shared_email:
                email = sorted(shared_email)[0]
                own = {refs[k][1] for k in (i, j) if refs[k][0] == "email"}
                if email in own and len(own) == 1:
                    # the other node's own profile publishes this exact address
                    link(i, j, W_STATED_EMAIL, f"profile states the email {email}")
                else:
                    link(i, j, W_EMAIL, f"shared email {email}")
            # only link on SPECIFIC, independently observed handles
            shared_handle = {
                h for h in (ei["usernames"] & ej["usernames"])
                if not is_generic(h) and h not in followed
            }
            if shared_handle:
                link(i, j, W_HANDLE, f"shared handle @{sorted(shared_handle)[0]}")
            shared_avatar = ei["avatars"] & ej["avatars"]
            if shared_avatar:
                link(i, j, W_AVATAR, "identical avatar image hash")
            # email local-part of one == a handle of the other (skip generic)
            # (counted once here; a local-part is never also a "shared handle")
            localpart_match = (
                (ei["localparts"] & ej["usernames"]) | (ej["localparts"] & ei["usernames"])
            )
            if any(len(h) >= MIN_HANDLE_LEN and not is_generic(h) for h in localpart_match):
                link(i, j, W_LOCALPART, "email name reused as handle")
            shared_name = ei["names"] & ej["names"]
            if shared_name:
                pair = (i, j)
                if pair_score.get(pair, 0) > 0:
                    # a name agreeing with other evidence corroborates it
                    link(i, j, W_NAME, f"shared name '{sorted(shared_name)[0]}'")
                else:
                    # a name ALONE is what namesakes share: a candidate of the
                    # searched name, nothing between two unrelated accounts
                    for hub, other in ((i, j), (j, i)):
                        if nodes[hub].get("type") == "name":
                            candidate(hub, other,
                                      f"same name '{sorted(shared_name)[0]}' only — may be a different person")

            # a name search surfaced this handle: namesake candidate only
            for hub, other in ((i, j), (j, i)):
                hit = {
                    h for h in extracted[hub]["candidate_handles"]
                    & extracted[other]["usernames"]
                    if not is_generic(h)
                }
                if hit and via != "name_match":
                    candidate(hub, other,
                              f"@{sorted(hit)[0]} found by name search — may be a different person")

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
        strongest = defaultdict(int)  # member -> its strongest tie in the cluster
        for (a, b), s in pair_score.items():
            if a in member_set and b in member_set:
                score += s
                signals.extend(pair_signals[(a, b)])
                strongest[a] = max(strongest[a], s)
                strongest[b] = max(strongest[b], s)
        weakest = min((strongest[m] for m in members), default=0)

        cands = []
        cand_seen = set()
        for idx in members:
            for other, reason in candidates.get(idx, []):
                if other not in member_set and other not in cand_seen:
                    cand_seen.add(other)
                    cands.append({
                        "key": nodes[other].get("key"),
                        "query": nodes[other].get("query"),
                        "reason": reason,
                    })

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
            "confidence": _confidence(weakest, len(members)),
            "candidates": cands,
            "signals": sorted(set(signals)),
            "contradictions": contradictions,
        })

    # most-connected clusters first, singletons last
    clusters.sort(key=lambda c: (len(c["members"]), c["score"]), reverse=True)
    return {"clusters": clusters, "cluster_count": len(clusters)}
