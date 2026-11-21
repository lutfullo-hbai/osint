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
from services.names import fold, name_bits, name_tokens, names_match, places_conflict, username_variants
from tools.contact_extract import contacts_from_text, extract_contacts

AGENT_MAX_NODES = 20
MAX_CANDIDATES = 8
MAX_FIELD_VALUES = 5
MAX_PROFILES = 12
MAX_SET_ASIDE = 10
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
B_ORG_AGREE = 1.5         # same workplace / school as described (7.6); people move, so no penalty
STRONG_LEAD = 6.0
POSSIBLE_LEAD = 3.0

FIELDS = ("name", "birth_year", "location", "work", "emails", "usernames", "profiles")

# 7.2: contacts read from the candidates' own pages
CONTACT_CANDIDATES = 3        # only the top leads get their websites read
MAX_SITE_READS = 3            # websites read per run
SITE_PAGES = 5                # pages per website
# profile-text labels whose value someone wrote about themselves
_BIO_RE = re.compile(r"\b(?:Bio|About|Description|Summary|Note|Contact|Website|Blog)s?:\s*([^;]+)", re.IGNORECASE)
_BARE_SITE_RE = re.compile(r"(?:www\.)?[a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.[a-z]{2,}(?:/\S*)?", re.IGNORECASE)
# not "Works:" (ORCID counts publications) and never a bare number ("Organizations: 10")
_WORK_RE = re.compile(r"\b(?:Company|Organi[sz]ation|Employer|Job|Institutions?|Education|School|"
                      r"University|Affiliation)s?:\s*([^;]*[^\W\d_][^;]*)", re.IGNORECASE)
_ORG_STOP = {"universiteti", "universitet", "university", "kompaniyasi", "company", "institute", "instituti",
             "school", "maktab", "maktabi", "college", "the", "of", "and", "llc", "mchj", "inc", "ltd", "group"}

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
        self.orgs = list(parsed.get("workplaces") or []) + list(parsed.get("schools") or [])

    @staticmethod
    def _org_keys(text: str) -> set[str]:
        keys = set()
        for word in re.split(r"[\s,;:/()\"'«».\-]+", str(text or "")):
            key = fold(word)
            if len(key) >= 3 and key not in _ORG_STOP:
                keys.add(key[:4])               # "Yandex" / "Яндексе" fold to andeh / andekse
        return keys

    def org_check(self, works: set[str]) -> tuple[float, str] | None:
        """7.6: the workplace or school the user named appears in the profile."""
        if not works or not self.orgs:
            return None
        for org in self.orgs:
            wanted = self._org_keys(org)
            for work in sorted(works):
                if wanted and wanted & self._org_keys(work):
                    return B_ORG_AGREE, f"works/studies at '{work}', as you said ({org})"
        return None

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

    # ---- 10.1: same handle, different person ----

    @staticmethod
    def _item_ids(item: dict) -> dict:
        info = str(item.get("info") or "")
        names = {n.strip() for n in _NAME_RE.findall(info) + ([item["name"]] if item.get("name") else [])
                 if len(str(n).split()) >= 2}
        return {"names": names,
                "locations": {loc.strip() for loc in _LOC_RE.findall(info)
                              if loc.strip() and loc.strip().casefold() not in _PLACEHOLDERS},
                "births": {int(y) for y in _BORN_RE.findall(info)}}

    def _profile_conflict(self, ids: dict, anchor_places: list[str], anchor_years: list[int]) -> str | None:
        if self.name and ids["names"] and not any(name_tokens(self.name) & name_tokens(n) for n in ids["names"]):
            return f"name '{sorted(ids['names'])[0]}' is not {self.name}"
        if ids["births"] and anchor_years and not any(abs(b - y) <= 1 for b in ids["births"] for y in anchor_years):
            return f"born {sorted(ids['births'])[0]}, not ~{anchor_years[-1]}"
        if ids["locations"] and anchor_places and all(
                places_conflict(loc, place) for loc in ids["locations"] for place in anchor_places):
            return f"location '{sorted(ids['locations'])[0]}', not {', '.join(anchor_places[:2])}"
        return None

    def split_profiles(self, nodes: list[dict]) -> int:
        """10.1: a handle like "torvalds" exists on dozens of sites and only
        some of those accounts belong to the person. Within each username
        record, a profile whose own name, birth year or town contradicts the
        description, or the profiles there that do match the name, is set
        aside (node["set_aside"], with the reason) before linking, so it adds
        neither fields nor contradictions to the candidate. Returns how many."""
        moved = 0
        for node in nodes:
            if node.get("type") != "username":
                continue
            items = [i for i in node.get("results") or [] if isinstance(i, dict)]
            ids = {id(i): self._item_ids(i) for i in items}
            anchors = [i for i in items if self.name and any(
                names_match(self.name, n) for n in ids[id(i)]["names"])]
            anchor_places = list(self.places) or sorted({loc for a in anchors for loc in ids[id(a)]["locations"]})
            anchor_years = list(self.years) or sorted({y for a in anchors for y in ids[id(a)]["births"]})
            kept, aside = [], []
            for item in node.get("results") or []:
                reason = None
                if isinstance(item, dict) and item not in anchors and not _from_search_only(item):
                    reason = self._profile_conflict(ids[id(item)], anchor_places, anchor_years)
                if reason:
                    aside.append({"platform": str(item.get("platform") or "")[:60], "url": item.get("url") or "",
                                  "reason": reason, "info": " ".join(str(item.get("info") or "").split())[:200]})
                else:
                    kept.append(item)
            if aside:
                node["results"] = kept
                node["count"] = len(kept)
                node["set_aside"] = aside
                node["anchored"] = sorted({str(a.get("url") or "") for a in anchors} - {""})
                moved += len(aside)
            elif anchors:
                node["anchored"] = sorted({str(a.get("url") or "") for a in anchors} - {""})
        return moved

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
    same = lambda a, b: (a.get("platform"), a.get("url")) == (b.get("platform"), b.get("url"))  # noqa: E731
    if source and not any(same(source, s) for s in entry["sources"]) and len(entry["sources"]) < 4:
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
            if item.get("retrieved_at"):
                source["retrieved_at"] = item["retrieved_at"]      # 8.1
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
            for work in _WORK_RE.findall(info):
                _add(raw["work"], work, source)
            if ntype in ("username", "email", "phone") and source["url"]:
                _add(raw["profiles"], source["platform"], source)
    fields = {}
    for field, values in raw.items():
        limit = MAX_PROFILES if field == "profiles" else MAX_FIELD_VALUES
        fields[field] = list(values.values())[:limit]
    return fields


def _merge_contact(out: list[dict], item: dict) -> None:
    for entry in out:
        if entry["kind"] == item["kind"] and entry["value"].casefold() == item["value"].casefold():
            for src in item.get("sources") or []:
                if src not in entry["sources"] and len(entry["sources"]) < 3:
                    entry["sources"].append(src)
            if item.get("confirmed"):
                entry["confirmed"] = True
            return
    out.append({"kind": item["kind"], "value": item["value"], "how": item.get("how", ""),
                "sources": list(item.get("sources") or [])[:3], "confirmed": bool(item.get("confirmed"))})


def _confirmed_profile(node: dict, item: dict) -> bool:
    """10.1: the profile is known to be this person's: the identifier was
    given by the user or is unique (e-mail, phone), or the profile itself
    carries the person's name."""
    if node.get("via") == "stated" or node.get("type") in ("email", "phone"):
        return True
    return str(item.get("url") or "") in set(node.get("anchored") or [])


def profile_contacts(members: list[dict], ignore_platforms: set[str] | None = None) -> list[dict]:
    """7.2: e-mails, phones, messenger and social links, websites that the
    person wrote in their own profiles (bio, channel description, website
    field), each with the profile page it was read on."""
    ignore_platforms = ignore_platforms or set()
    out: list[dict] = []
    for node in members:
        for item in node.get("results") or []:
            if _from_search_only(item) or item.get("source") in ("dns_contact", "run_summary"):
                continue
            if str(item.get("status") or "found").lower() not in ("found", "success", "registered"):
                continue
            if str(item.get("platform") or "").casefold() in ignore_platforms:
                continue
            url = str(item.get("url") or "")
            # only the self-written parts: counters like "Followers: 901234567" are not phones
            parts = _BIO_RE.findall(str(item.get("info") or "")) + [str(item.get("website") or "")]
            # a website field often has no scheme: "torvalds.org"
            text = " ; ".join(p if "://" in p or not _BARE_SITE_RE.fullmatch(p.strip()) else "https://" + p.strip()
                              for p in parts if p)
            if not text.strip():
                continue
            platform = str(item.get("platform") or "profile")[:60]
            confirmed = _confirmed_profile(node, item)
            how = f"written in the {platform} profile" + ("" if confirmed else " (profile not confirmed as this person)")
            for found in contacts_from_text(text, url, how=how):
                _merge_contact(out, {**found, "confirmed": confirmed})
    return out[:20]


def evidence_chain(member_keys: list[str], scan: dict) -> list[dict]:
    """7.1: how each record was reached from what you searched, step by step."""
    nodes = {n["key"]: n for n in scan.get("nodes") or []}
    parent = {}
    for edge in scan.get("edges") or []:
        parent.setdefault(edge.get("to"), edge.get("from"))
    chain = []
    for key in member_keys:
        path, seen, cur = [], set(), key
        while cur in nodes and cur not in seen and len(path) < 6:
            seen.add(cur)
            node = nodes[cur]
            path.append({"type": node.get("type"), "value": node.get("query"),
                         "via": _VIA_LABEL.get(node.get("via"), node.get("via")) or "you searched"})
            cur = parent.get(cur)
        chain.append({"record": f"{nodes[key].get('type')} {nodes[key].get('query')}" if key in nodes else key,
                      "path": list(reversed(path))})
    return chain


async def read_candidate_sites(candidates: list[dict], say=None) -> int:
    """7.2/7.7: read the personal websites the top candidates link to, and add
    the contacts published there. Bounded: MAX_SITE_READS sites per run."""
    reads = 0
    for candidate in candidates[:CONTACT_CANDIDATES]:
        if candidate["level"] == "weak":
            continue
        # 10.1: a site in the bio of an unconfirmed same-handle profile may be a stranger's
        sites = [c["value"] for c in candidate.get("contacts") or [] if c["kind"] == "website" and c.get("confirmed")]
        for site in sites[:2]:
            if reads >= MAX_SITE_READS:
                return reads
            reads += 1
            if say:
                await say("check", f"Reading contacts on {site} (linked from a profile of {candidate['label']})")
            try:
                found = await extract_contacts(site, max_pages=SITE_PAGES)
            except Exception as exc:  # noqa: BLE001 - one site must not stop the run
                if say:
                    await say("skip", f"Could not read {site}: {type(exc).__name__}")
                continue
            for item in found.get("contacts") or []:
                if item["kind"] != "website":
                    _merge_contact(candidate["contacts"], {**item, "how": f"published on {site}", "confirmed": True})
            if say and found.get("notes"):
                await say("skip", f"{site}: " + "; ".join(found["notes"][:2]))
    return reads


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
        works = {v["value"] for v in fields["work"]}
        for check in (target.name_check(names), target.age_check(births), target.place_check(locations),
                      target.org_check(works)):
            if check:
                score += check[0]
                (why if check[0] > 0 else conflicts).append(check[1])
        vias = {m.get("via") for m in members}
        if not stated and vias <= {"name_match", "name_variant", None} and len(members) == 1:
            why.append("found only through the name — may be a namesake")
        missing = [f for f in FIELDS if not fields[f]]
        set_aside = [a for m in members for a in m.get("set_aside") or []][:MAX_SET_ASIDE]
        unchecked = sorted({s for m in members for s in m.get("unchecked") or []})
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
            "contacts": profile_contacts(members, ignored),
            # 10.1: same handle, other person - shown, never merged
            "set_aside": set_aside,
            # 10.2: sources that did not answer; the score may be too low because of them
            "unchecked": unchecked,
            "chain": evidence_chain([m["key"] for m in members], scan),
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
                               progress=on_progress, expand=target.expand, max_nodes=AGENT_MAX_NODES,
                               prepare=target.split_profiles)
    set_aside = sum(len(n.get("set_aside") or []) for n in scan["nodes"])
    if set_aside:
        await say("skip", f"Set aside {set_aside} same-username profile(s) that describe someone else "
                          "(other name, age or town)")
    unchecked = sorted({s for n in scan["nodes"] for s in n.get("unchecked") or []})
    if unchecked:
        await say("skip", "Not checked this time: " + ", ".join(unchecked[:5])
                  + " — scores can be lower than on a run where they answer")
    # the user's own identifiers are stated, not found by a pivot
    for node in scan["nodes"]:
        if node["key"] in stated_keys:
            node["via"] = "stated"
    await say("link", f"Linked {scan['node_count']} record(s) into {scan['cluster_count']} identity group(s)"
              + (f"; AI gave a second opinion on {scan['ai_reviewed']}" if scan.get("ai_reviewed") else ""))
    candidates, overview = rank(scan, target, stated_keys)
    await read_candidate_sites(candidates, say)
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
