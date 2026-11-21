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

from services.names import (
    is_common_token,
    name_bits,
    name_tokens,
    names_match,
    places_conflict,
)

# Handles shorter than this collide too easily to be trusted as a link.
MIN_HANDLE_LEN = 4

# Evidence weights, in bits: roughly log2 of how much likelier an observation
# is when two records are the SAME person than when they are two different
# people (Fellegi-Sunter). Positive bits support a link, negative bits
# (contradictions) argue against it.
B_KB = 6.0             # a curated knowledge base (Wikidata) lists the account
# 10.5b: a knowledge base lists several people with this name and we picked the
# one whose birth year fits the age you gave. For RANKING this is as good as a
# unique-name hit (it is our best guess at who they are), so the right person
# ranks first. CONFIDENCE is handled separately: rank() caps an age-confirmed
# candidate at "possible" unless independent evidence corroborates it, because
# an age (often an estimate) is not proof. So the weight here is ranking power,
# and never by itself produces a "strong" level.
B_AGE_CONFIRMED = B_KB
B_STATED_EMAIL = 6.0   # a profile itself publishes the email being investigated
B_EMAIL = 5.0          # the same specific email address on two records
B_ROLE_EMAIL = 1.0     # the same role address (info@, admin@): many people
B_LINKED = 4.5         # a profile explicitly links out to the other account
B_AVATAR = 3.0         # the same perceptual avatar hash
B_PLACE_AGREE = 0.5    # the same stated city/country
B_BIRTH_AGREE = 1.0    # the same stated birth year
B_PLACE_CONFLICT = -1.5   # stated locations share no place at all
B_BIRTH_CONFLICT = -4.0   # stated birth years differ by more than a year
B_NAME_CONFLICT = -1.0    # both state a full name and the names share nothing

# Decision rule: a link needs enough total evidence AND either one strong
# signal or two independent medium ones. A name never links on its own.
STRONG_BITS = 4.0
MEDIUM_BITS = 1.5
LINK_BITS = 3.0
COMBINED_BITS = 3.5
# Cluster confidence from the weakest member's strongest tie (in bits)
HIGH_BITS = 6.0
MEDIUM_CONF_BITS = 4.5

ROLE_LOCALPARTS = {
    "info", "admin", "contact", "support", "hello", "office", "sales", "mail",
    "team", "help", "noreply", "no-reply", "press", "hr", "jobs", "billing",
}

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
# only a field label at the start of an "a: b; c: d" part - not "Company name:"
# or "Previous location:" inside a bio (QA 10.1)
_LOC_RE = re.compile(r"(?:^|;)\s*Location:\s*([^;]+)", re.IGNORECASE)
_NAME_RE = re.compile(r"(?:^|;)\s*Name:\s*([^;]+)", re.IGNORECASE)
_LINKED_RE = re.compile(r"Linked:\s*([^;]+)", re.IGNORECASE)
_BORN_RE = re.compile(r"\b(?:Born|Birth year|Year of birth):\s*(\d{4})", re.IGNORECASE)
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
    "instagram.com": ("", frozenset({"p", "reel", "reels", "explore", "stories", "accounts", "tv", "direct", "popular"})),
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


def _from_search_only(item: dict) -> bool:
    """A hit that only a search engine produced (no site check confirmed it)."""
    if item.get("source") == "web_search":
        return True
    sources = item.get("sources")
    return isinstance(sources, list) and bool(sources) and set(sources) == {"search-index"}


def _extract(node: dict) -> dict:
    """Pull every identifier a node carries into normalized buckets."""
    ids = {
        "usernames": set(),
        "emails": set(),
        "names": set(),
        "domains": set(),
        "avatars": set(),
        "locations": set(),
        "births": set(),
        # handles a profile itself lists as its own other accounts
        "linked_handles": set(),
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
        from_search = _from_search_only(item)
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
            ids["linked_handles"].add(norm_handle(linked))

        if from_search or item.get("source") == "dns_contact":
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
                    ids["linked_handles"].add(norm_handle(handle))
        for year in _BORN_RE.findall(info):
            ids["births"].add(int(year))
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


def handle_bits(handle: str) -> float:
    """How telling a shared handle is: long, mixed handles are rare."""
    n = len(handle)
    bits = 1.0 if n <= 5 else 1.75 if n <= 7 else 2.25 if n <= 10 else 2.75
    if re.search(r"\d", handle) and re.search(r"[a-z]", handle):
        bits += 0.5
    if handle.isalpha() and is_common_token(handle):
        bits = 0.5   # "aziz", "karimov": a common name used as a handle
    return min(bits, 3.0)


def _confidence(strength: float, members: int) -> str:
    if members < 2:
        return "single"
    if strength >= HIGH_BITS:
        return "high"
    if strength >= MEDIUM_CONF_BITS:
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


def _decide(evidence: list[tuple[str, float, str]]) -> tuple[bool, float]:
    """Apply the link rule to one pair's evidence -> (link?, total bits)."""
    total = round(sum(bits for _k, bits, _r in evidence), 2)
    positives = [(k, b) for k, b, _r in evidence if b > 0]
    strong = any(b >= STRONG_BITS for _k, b in positives)
    medium_kinds = {k for k, b in positives if b >= MEDIUM_BITS}
    beyond_name = any(k not in ("name", "place", "birth") for k, _b in positives)
    kinds = {k for k, _b in positives}
    linked = beyond_name and total >= LINK_BITS and (
        strong
        or len(medium_kinds) >= 2
        # two independent signals that together come close to "strong"
        or (len(kinds) >= 2 and total >= COMBINED_BITS)
    )
    return linked, total


def correlate(nodes: list[dict]) -> dict:
    """Cluster nodes that plausibly describe the same entity.

    Returns {"clusters": [...], "cluster_count": n}. Each cluster lists its
    member node keys, the identifiers that tie them, a confidence level, the
    human-readable signals behind it, any contradictions (e.g. two different
    stated locations) and candidates that were NOT merged, with the reason.

    Evidence rules:
    - every signal carries a weight in bits; common names and short handles
      are worth little, a knowledge-base listing or a stated email a lot;
    - a pair is merged only with >= LINK_BITS in total AND one strong signal
      or two independent medium ones; a name alone never merges;
    - contradictions (different birth year, location, name) subtract;
    - a pivot is not evidence of itself: the handle that was followed from A
      to B does not also count as a "shared handle";
    - how a pivot was found decides its weight ("via"): knowledge base and
      profile links are evidence; a display-name match or a username guessed
      from a name is only a candidate; a tagged @mention is nothing;
    - confidence is set by the cluster's WEAKEST member.
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
    # a Deep Scan node also records how it was reached (parent + via): this
    # covers pivots that were not in the parent's "pivots" list (guessed handles)
    index_of = {node.get("key"): idx for idx, node in enumerate(nodes)}
    for idx, node in enumerate(nodes):
        parent_idx = index_of.get(node.get("parent"))
        if parent_idx is not None and node.get("via"):
            pivot_via[parent_idx].setdefault(refs[idx], node["via"])

    # global handle frequency across all nodes -> spot over-common handles
    handle_freq: dict[str, set] = defaultdict(set)
    for e in extracted:
        for handle, platforms in e["handle_platforms"].items():
            handle_freq[handle] |= platforms

    def is_generic(handle: str) -> bool:
        return (
            handle in STOPLIST_HANDLES
            or len(handle) < MIN_HANDLE_LEN
            or len(handle_freq.get(handle, ())) >= GENERIC_PLATFORM_THRESHOLD
        )

    pair_total: dict[tuple[int, int], float] = {}
    pair_signals: dict[tuple[int, int], list[str]] = {}
    pair_conflicts: dict[tuple[int, int], list[str]] = {}
    # hub index -> [(candidate index, reason)] — shown, never merged
    candidates: dict[int, list[tuple[int, str]]] = defaultdict(list)

    def candidate(hub: int, other: int, reason: str) -> None:
        if all(c != other for c, _ in candidates[hub]):
            candidates[hub].append((other, reason))

    for i in range(n):
        for j in range(i + 1, n):
            ei, ej = extracted[i], extracted[j]
            evidence: list[tuple[str, float, str]] = []

            # how one node led to the other, if it did
            via, parent, child = None, None, None
            if refs[j] in pivot_via[i]:
                via, parent, child = pivot_via[i][refs[j]], i, j
            elif refs[i] in pivot_via[j]:
                via, parent, child = pivot_via[j][refs[i]], j, i
            # the followed handle itself is not independent evidence
            followed = {refs[child][1]} if child is not None and refs[child][0] == "username" else set()
            # two username scans of the same handle spelled differently
            # (linus.torvalds / linustorvalds) share it by construction
            if refs[i][0] == refs[j][0] == "username" and refs[i][1] == refs[j][1]:
                followed = followed | {refs[i][1]}

            if via == "knowledge_base":
                evidence.append(("kb", B_KB, f"listed on a knowledge base: @{refs[child][1]}"))
            elif via == "age_confirmed":
                evidence.append(("kb", B_AGE_CONFIRMED,
                                 f"knowledge base: this name at the age you gave -> @{refs[child][1]}"))
            elif via == "profile_link":
                evidence.append(("linked", B_LINKED, f"profile links to {refs[child][1]}"))
            else:
                # one profile lists the other account's own handle as its own
                for a_, b_ in ((i, j), (j, i)):
                    h = refs[b_][1] if refs[b_][0] == "username" else None
                    if h and h in extracted[a_]["linked_handles"] and not is_generic(h):
                        evidence.append(("linked", B_LINKED, f"profile links to {h}"))
                        followed = followed | {h}
                        break

            shared_email = ei["emails"] & ej["emails"]
            if shared_email:
                email = sorted(shared_email)[0]
                own = {refs[k][1] for k in (i, j) if refs[k][0] == "email"}
                if email.split("@", 1)[0] in ROLE_LOCALPARTS:
                    evidence.append(("email", B_ROLE_EMAIL, f"shared role address {email}"))
                elif email in own and len(own) == 1:
                    evidence.append(("email", B_STATED_EMAIL, f"profile states the email {email}"))
                else:
                    evidence.append(("email", B_EMAIL, f"shared email {email}"))

            # only SPECIFIC, independently observed handles count
            shared_handle = sorted(
                (h for h in (ei["usernames"] & ej["usernames"])
                 if not is_generic(h) and h not in followed),
                key=handle_bits, reverse=True,
            )
            if shared_handle:
                h = shared_handle[0]
                evidence.append(("handle", handle_bits(h), f"shared handle @{h}"))

            if ei["avatars"] & ej["avatars"]:
                evidence.append(("avatar", B_AVATAR, "identical avatar image hash"))

            # email local-part of one == a handle of the other (counted once)
            localpart_match = sorted(
                (h for h in (ei["localparts"] & ej["usernames"]) | (ej["localparts"] & ei["usernames"])
                 if not is_generic(h) and h not in ROLE_LOCALPARTS),
                key=handle_bits, reverse=True,
            )
            if localpart_match and not shared_handle:
                h = localpart_match[0]
                evidence.append(("localpart", handle_bits(h), "email name reused as handle"))

            # names: compared across scripts and spellings, weighted by rarity
            best_name, best_bits = None, 0.0
            for a in ei["names"]:
                for b in ej["names"]:
                    common = names_match(a, b)
                    if common and name_bits(common) > best_bits:
                        best_name, best_bits = a, name_bits(common)
            if best_name:
                evidence.append(("name", best_bits, f"shared name '{best_name}'"))
            elif ei["names"] and ej["names"] and not any(
                name_tokens(a) & name_tokens(b) for a in ei["names"] for b in ej["names"]
            ):
                evidence.append(("name", B_NAME_CONFLICT, "different stated names"))

            # birth year and place agree or contradict
            if ei["births"] and ej["births"]:
                if any(abs(x - y) <= 1 for x in ei["births"] for y in ej["births"]):
                    evidence.append(("birth", B_BIRTH_AGREE, "same birth year"))
                else:
                    evidence.append(("birth", B_BIRTH_CONFLICT, "different birth years: "
                                     + ", ".join(str(y) for y in sorted(ei["births"] | ej["births"]))))
            if ei["locations"] and ej["locations"]:
                if all(places_conflict(a, b) for a in ei["locations"] for b in ej["locations"]):
                    evidence.append(("place", B_PLACE_CONFLICT, "different stated locations: "
                                     + "; ".join(sorted(ei["locations"] | ej["locations"]))))
                else:
                    evidence.append(("place", B_PLACE_AGREE, "same stated location"))

            linked, total = _decide(evidence)
            key = (i, j)
            if linked:
                uf.union(i, j)
                pair_total[key] = total
                pair_signals[key] = [r for _k, b, r in evidence if b > 0]
                pair_conflicts[key] = [r for _k, b, r in evidence if b < 0]
                continue

            # not merged: say why it is still worth a look, if it is
            positive = [(k, r) for k, b, r in evidence if b > 0]
            conflicts = [r for _k, b, r in evidence if b < 0]
            suffix = (" — but " + "; ".join(conflicts)) if conflicts else ""
            if via in ("name_match", "name_variant"):
                why = ("display name matches" if via == "name_match"
                       else "username guessed from the name")
                candidate(parent, child, f"{why} — may be a different person{suffix}")
            elif positive and any(k not in ("name", "place", "birth") for k, _r in positive):
                hub = parent if parent is not None else i
                other = child if child is not None else j
                candidate(hub, other, "; ".join(r for _k, r in positive)
                          + f" — not enough to merge, may be a different person{suffix}")
            elif positive and any(k == "name" for k, _r in positive):
                # a name ALONE is what namesakes share: a candidate of the
                # searched name, nothing between two unrelated accounts
                for hub, other in ((i, j), (j, i)):
                    if nodes[hub].get("type") == "name":
                        candidate(hub, other, f"{positive[0][1].replace('shared name', 'same name')} only"
                                  f" — may be a different person{suffix}")

            # a name search surfaced this handle: namesake candidate only
            for hub, other in ((i, j), (j, i)):
                hit = {
                    h for h in extracted[hub]["candidate_handles"]
                    & extracted[other]["usernames"]
                    if not is_generic(h)
                }
                if hit and via not in ("name_match", "name_variant"):
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
        for idx in members:
            e = extracted[idx]
            usernames |= e["usernames"]
            emails |= e["emails"]
            names |= e["names"]
            domains |= e["domains"]
            platforms |= e["platforms"]

        score = 0.0
        signals: list[str] = []
        contradictions: list[str] = []
        strongest = defaultdict(float)  # member -> its strongest tie in the cluster
        for (a, b), total in pair_total.items():
            if a in member_set and b in member_set:
                score += total
                signals.extend(pair_signals[(a, b)])
                contradictions.extend(pair_conflicts[(a, b)])
                strongest[a] = max(strongest[a], total)
                strongest[b] = max(strongest[b], total)
        weakest = min((strongest[m] for m in members), default=0.0)

        # members linked through a third node can still disagree
        locs = {loc for m in members for loc in extracted[m]["locations"]}
        if any(places_conflict(a, b) for a in locs for b in locs) and not any(
            c.startswith("different stated locations") for c in contradictions
        ):
            contradictions.append("different stated locations: " + "; ".join(sorted(locs)))
        years = {y for m in members for y in extracted[m]["births"]}
        if years and max(years) - min(years) > 1 and not any(
            c.startswith("different birth years") for c in contradictions
        ):
            contradictions.append("different birth years: " + ", ".join(str(y) for y in sorted(years)))

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
            "score": round(score, 2),
            "confidence": _confidence(weakest, len(members)),
            "candidates": cands,
            "signals": sorted(set(signals)),
            "contradictions": sorted(set(contradictions)),
        })

    # most-connected clusters first, singletons last
    clusters.sort(key=lambda c: (len(c["members"]), c["score"]), reverse=True)
    return {"clusters": clusters, "cluster_count": len(clusters)}
