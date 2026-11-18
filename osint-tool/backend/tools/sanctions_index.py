"""Local sanctions and PEP index built from free, official sources.

Replaces the paid OpenSanctions API. Sources (all free to download):
- UN Security Council consolidated list (XML)
- US OFAC SDN list (XML; the endpoint redirects to a short-lived signed URL)
- EU consolidated financial sanctions list (XML)
- UK Sanctions List (CSV; replaced the OFSI list on 2026-01-28)
- PEPs: people with "position held" (P39) in Wikidata (CC0), per country

Everything is stored in one SQLite file with an FTS5 table over folded name
tokens, so "Мирзиёев" and "Mirziyoyev" meet. A hit is only ever "a listed
entry with the same name" — never "this person is sanctioned"; a different
birth year rules a candidate out.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import itertools
import json
import os
import re
import sqlite3
import time
import xml.etree.ElementTree as ET

import httpx

from services.names import is_common_token, name_tokens, names_match
from tools.base import IndexNotReady, ToolError

DB_PATH = os.environ.get("SANCTIONS_DB_PATH", "/app/data/sanctions.db")
USER_AGENT = "osint-tool/1.0 (self-hosted research; sanctions list sync)"
DOWNLOAD_TIMEOUT = httpx.Timeout(180.0, connect=20.0)
MAX_CANDIDATES = 400
MAX_QUERY_TOKENS = 6     # a real name has a few words; longer input is noise
MAX_SUBSETS = 20
MAX_HITS = 10

SOURCES = {
    "un": {
        "label": "UN Security Council consolidated list",
        "url": "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
        "page": "https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list",
    },
    "ofac": {
        "label": "US OFAC SDN list",
        "url": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML",
        "page": "https://sanctionssearch.ofac.treas.gov/",
    },
    "eu": {
        "label": "EU consolidated financial sanctions list",
        "url": "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw",
        "page": "https://www.sanctionsmap.eu/",
    },
    "uk": {
        "label": "UK Sanctions List",
        "url": "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv",
        "page": "https://www.gov.uk/government/publications/the-uk-sanctions-list",
    },
}

# Wikidata country items for PEP import (Central Asia by default).
PEP_COUNTRIES = {
    "UZ": "Q265", "KZ": "Q232", "KG": "Q813", "TJ": "Q863", "TM": "Q874",
}
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
# QLever (academic, no SLA) mirrors Wikidata and answers the same SPARQL; used
# when the official endpoint rate-limits or is down.
SPARQL_ENDPOINTS = [WIKIDATA_SPARQL, "https://qlever.dev/api/wikidata"]
SPARQL_PREFIXES = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""

_YEAR_RE = re.compile(r"(1[89]\d\d|20[0-2]\d)")


def _years(*values) -> set[int]:
    out = set()
    for value in values:
        for match in _YEAR_RE.findall(str(value or "")):
            out.add(int(match))
    return out


def _entity(source, ext_id, kind, names, years=(), nationalities=(), programs=(), url="", note=""):
    return {
        "source": source, "ext_id": str(ext_id), "kind": kind,
        "names": [n for n in names if n[0] and n[0].strip()],
        "years": sorted(set(years)), "nationalities": sorted({n for n in nationalities if n}),
        "programs": sorted({p for p in programs if p}), "url": url, "note": note,
    }


# ---------------- parsers (bytes -> list of entity dicts) ----------------

def parse_un(data: bytes) -> list[dict]:
    root = ET.fromstring(data)
    out = []
    for tag, kind in (("INDIVIDUAL", "person"), ("ENTITY", "entity")):
        for el in root.iter(tag):
            parts = [el.findtext(t) or "" for t in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")]
            names = [(" ".join(p for p in parts if p).strip(), True, True)]
            for alias in el.iter(f"{tag}_ALIAS"):
                name = (alias.findtext("ALIAS_NAME") or "").strip()
                if name:
                    names.append((name, (alias.findtext("QUALITY") or "").lower() != "low", False))
            years = _years(*[d.findtext("YEAR") or d.findtext("DATE") for d in el.iter(f"{tag}_DATE_OF_BIRTH")])
            nats = [v.text for v in el.findall("NATIONALITY/VALUE")]
            out.append(_entity("un", el.findtext("REFERENCE_NUMBER") or el.findtext("DATAID"), kind, names,
                               years, nats, [el.findtext("UN_LIST_TYPE")], SOURCES["un"]["page"]))
    return out


def parse_ofac(data: bytes) -> list[dict]:
    root = ET.fromstring(data)
    ns = {"o": root.tag[1:].split("}")[0]} if root.tag.startswith("{") else {}
    q = (lambda t: f"o:{t}") if ns else (lambda t: t)
    out = []
    for el in root.findall(q("sdnEntry"), ns):
        def full(node):
            return " ".join(x for x in ((node.findtext(q("firstName"), "", ns) or ""),
                                        (node.findtext(q("lastName"), "", ns) or "")) if x).strip()
        names = [(full(el), True, True)]
        for aka in el.findall(f"{q('akaList')}/{q('aka')}", ns):
            names.append((full(aka), (aka.findtext(q("category"), "", ns) or "").lower() == "strong", False))
        sdn_type = (el.findtext(q("sdnType"), "", ns) or "").lower()
        kind = {"individual": "person", "entity": "entity", "vessel": "vessel"}.get(sdn_type, "other")
        years = _years(*[d.findtext(q("dateOfBirth"), "", ns)
                         for d in el.findall(f"{q('dateOfBirthList')}/{q('dateOfBirthItem')}", ns)])
        nats = [n.findtext(q("country"), "", ns)
                for n in el.findall(f"{q('nationalityList')}/{q('nationality')}", ns)]
        programs = [p.text for p in el.findall(f"{q('programList')}/{q('program')}", ns)]
        uid = el.findtext(q("uid"), "", ns)
        out.append(_entity("ofac", uid, kind, names, years, nats, programs,
                           f"https://sanctionssearch.ofac.treas.gov/Details.aspx?id={uid}"))
    return out


def parse_eu(data: bytes) -> list[dict]:
    root = ET.fromstring(data)
    ns = root.tag[1:].split("}")[0] if root.tag.startswith("{") else ""
    q = (lambda t: f"{{{ns}}}{t}") if ns else (lambda t: t)
    out = []
    for el in root.iter(q("sanctionEntity")):
        subject = el.find(q("subjectType"))
        code = (subject.get("code") if subject is not None else "") or ""
        kind = {"person": "person", "enterprise": "entity"}.get(code, "other")
        names = []
        for i, alias in enumerate(el.findall(q("nameAlias"))):
            whole = (alias.get("wholeName") or "").strip()
            if whole:
                names.append((whole, alias.get("strong", "true") == "true", i == 0))
        years = _years(*[b.get("year") or b.get("birthdate") for b in el.findall(q("birthdate"))])
        nats = [c.get("countryDescription") for c in el.findall(q("citizenship"))]
        programs = [r.get("programme") for r in el.findall(q("regulation"))]
        ref = el.get("euReferenceNumber") or el.get("logicalId")
        out.append(_entity("eu", ref, kind, names, years, nats, programs, SOURCES["eu"]["page"],
                           note=f"EU reference {ref}"))
    return out


def parse_uk(data: bytes) -> list[dict]:
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines(keepends=True)
    if lines and lines[0].lower().startswith("report date"):
        lines = lines[1:]          # first line is "Report Date: ...", header follows
    reader = csv.DictReader(io.StringIO("".join(lines)))
    grouped: dict[str, dict] = {}
    for row in reader:
        uid = (row.get("Unique ID") or "").strip()
        if not uid:
            continue
        item = grouped.setdefault(uid, {"names": [], "years": set(), "nats": set(), "programs": set(), "kind": "other"})
        parts = [row.get(f"Name {i}", "") for i in (1, 2, 3, 4, 5)] + [row.get("Name 6", "")]
        name = " ".join(p.strip() for p in parts if p and p.strip())
        primary = (row.get("Name type") or "").lower().startswith("primary")
        strong = (row.get("Alias strength") or "").lower() != "weak"
        if name and all(name != n[0] for n in item["names"]):
            item["names"].append((name, strong, primary))
        non_latin = (row.get("Name non-latin script") or "").strip()
        if non_latin and all(non_latin != n[0] for n in item["names"]):
            item["names"].append((non_latin, True, False))
        item["years"] |= _years(row.get("D.O.B"))
        item["nats"] |= {n.strip() for n in (row.get("Nationality(/ies)") or "").split(",") if n.strip()}
        if row.get("Regime Name"):
            item["programs"].add(row["Regime Name"])
        designation = (row.get("Designation Type") or "").lower()
        item["kind"] = {"individual": "person", "entity": "entity", "ship": "vessel"}.get(designation, item["kind"])
    return [
        _entity("uk", uid, v["kind"], v["names"], v["years"], v["nats"], v["programs"],
                SOURCES["uk"]["page"], note=f"UK Unique ID {uid}")
        for uid, v in grouped.items()
    ]


PARSERS = {"un": parse_un, "ofac": parse_ofac, "eu": parse_eu, "uk": parse_uk}


def pep_query(country_qid: str) -> str:
    return SPARQL_PREFIXES + f"""
SELECT ?p (SAMPLE(?posLabel) AS ?position) (MIN(?start) AS ?from) (MAX(?end) AS ?to)
       (SAMPLE(?dob) AS ?born)
       (GROUP_CONCAT(DISTINCT ?name; separator="|") AS ?names)
WHERE {{
  ?p wdt:P31 wd:Q5; p:P39 ?st. ?st ps:P39 ?pos.
  ?pos wdt:P17|wdt:P1001 wd:{country_qid}.
  OPTIONAL {{ ?st pq:P580 ?start }} OPTIONAL {{ ?st pq:P582 ?end }}
  OPTIONAL {{ ?p wdt:P569 ?dob }}
  OPTIONAL {{ ?pos rdfs:label ?posLabel FILTER(lang(?posLabel) = "en") }}
  {{ ?p rdfs:label ?name }} UNION {{ ?p skos:altLabel ?name }}
  FILTER(lang(?name) IN ("en", "uz", "ru", "uz-cyrl"))
}} GROUP BY ?p
"""


def parse_peps(payload: dict, country: str) -> list[dict]:
    out = []
    for b in (payload.get("results") or {}).get("bindings") or []:
        qid = b["p"]["value"].rsplit("/", 1)[-1]
        names = [(n, True, i == 0) for i, n in enumerate(dict.fromkeys(
            (b.get("names") or {}).get("value", "").split("|"))) if n]
        position = (b.get("position") or {}).get("value", "")
        start = (b.get("from") or {}).get("value", "")[:4]
        end = (b.get("to") or {}).get("value", "")[:4]
        span = f" ({start or '?'}–{end})" if start or end else ""
        out.append(_entity("pep", qid, "person", names, _years((b.get("born") or {}).get("value")),
                           [country], [position], f"https://www.wikidata.org/wiki/{qid}",
                           note=f"Position held: {position or 'public office'}{span}"))
    return out


# ---------------- storage ----------------

def _connect(path: str = DB_PATH) -> sqlite3.Connection:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(path: str = DB_PATH) -> None:
    with _connect(path) as conn:
        conn.executescript("""
CREATE TABLE IF NOT EXISTS source (
  name TEXT PRIMARY KEY, url TEXT, fetched_at REAL, sha256 TEXT, records INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS entity (
  id INTEGER PRIMARY KEY, source TEXT, ext_id TEXT, kind TEXT, years TEXT,
  nationalities TEXT, programs TEXT, url TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS entity_source ON entity(source);
CREATE TABLE IF NOT EXISTS name (entity_id INTEGER, name TEXT, strong INTEGER, is_primary INTEGER);
CREATE INDEX IF NOT EXISTS name_entity ON name(entity_id);
CREATE VIRTUAL TABLE IF NOT EXISTS name_fts USING fts5(tokens, entity_id UNINDEXED, name UNINDEXED);
""")


def store_source(source: str, entities: list[dict], sha256: str, url: str, path: str = DB_PATH) -> int:
    """Replace one source's entities in a single transaction."""
    init_db(path)
    with _connect(path) as conn:
        old = [r[0] for r in conn.execute("SELECT id FROM entity WHERE source=?", (source,))]
        if old:
            marks = ",".join("?" * len(old))
            conn.execute(f"DELETE FROM name WHERE entity_id IN ({marks})", old)
            conn.execute(f"DELETE FROM name_fts WHERE entity_id IN ({marks})", old)
            conn.execute("DELETE FROM entity WHERE source=?", (source,))
        for e in entities:
            cur = conn.execute(
                "INSERT INTO entity (source, ext_id, kind, years, nationalities, programs, url, note) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (source, e["ext_id"], e["kind"], json.dumps(e["years"]), json.dumps(e["nationalities"]),
                 json.dumps(e["programs"][:5]), e["url"], e["note"]),
            )
            eid = cur.lastrowid
            for name, strong, primary in e["names"]:
                conn.execute("INSERT INTO name VALUES (?,?,?,?)", (eid, name, int(strong), int(primary)))
                tokens = name_tokens(name)
                if tokens:
                    conn.execute("INSERT INTO name_fts (tokens, entity_id, name) VALUES (?,?,?)",
                                 (" ".join(sorted(tokens)), eid, name))
        conn.execute("INSERT OR REPLACE INTO source VALUES (?,?,?,?,?,?)",
                     (source, url, time.time(), sha256, len(entities), "ok"))
    return len(entities)


def source_status(path: str = DB_PATH) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    with _connect(path) as conn:
        try:
            return {r["name"]: dict(r) for r in conn.execute("SELECT * FROM source")}
        except sqlite3.OperationalError:
            return {}


# ---------------- refresh (worker) ----------------

async def _download(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(url)
    if response.status_code != 200:
        raise ToolError(f"HTTP {response.status_code}")
    return response.content


async def refresh_sources(path: str = DB_PATH) -> dict:
    """Download every list; re-parse only what changed (sha256)."""
    init_db(path)
    known = source_status(path)
    report = {}
    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT}) as client:
        for key, meta in SOURCES.items():
            try:
                data = await _download(client, meta["url"])
                digest = hashlib.sha256(data).hexdigest()
                if known.get(key, {}).get("sha256") == digest:
                    report[key] = "unchanged"
                    continue
                entities = await asyncio.to_thread(PARSERS[key], data)
                if not entities:
                    raise ToolError("parsed 0 records (format changed?)")
                count = await asyncio.to_thread(store_source, key, entities, digest, meta["url"], path)
                report[key] = f"{count} records"
            except Exception as exc:  # noqa: BLE001 - keep the previous copy of that list
                report[key] = f"error: {type(exc).__name__}: {exc}"[:200]
    return report


async def refresh_peps(path: str = DB_PATH) -> dict:
    """Weekly: PEPs per country from Wikidata (CC0)."""
    init_db(path)
    report = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0), headers={
        "User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}) as client:
        for country, qid in PEP_COUNTRIES.items():
            try:
                payload, last_error = None, "no endpoint"
                for endpoint in SPARQL_ENDPOINTS:
                    response = await client.get(endpoint, params={"query": pep_query(qid)})
                    if response.status_code == 200:
                        payload = response.json()
                        break
                    last_error = f"{endpoint}: HTTP {response.status_code}"
                if payload is None:
                    raise ToolError(last_error)
                found = parse_peps(payload, country)
                if found:
                    # one source per country: a failure for one country
                    # keeps that country's previous PEPs instead of wiping them
                    digest = hashlib.sha256(json.dumps([e["ext_id"] for e in found]).encode()).hexdigest()
                    await asyncio.to_thread(store_source, f"pep:{country}", found, digest, WIKIDATA_SPARQL, path)
                report[country] = len(found)
            except Exception as exc:  # noqa: BLE001
                report[country] = f"error: {type(exc).__name__}"
            await asyncio.sleep(2)   # be gentle with the public endpoint
    return report


def has_peps(path: str = DB_PATH) -> bool:
    return any(key.startswith("pep") for key in source_status(path))


# ---------------- search ----------------

def _word_count(name: str) -> int:
    """Words of a name that identify (patronymics and connectors excluded)."""
    words = [w for w in re.split(r"[\s,.\-_/]+", str(name or "")) if w]
    return sum(1 for w in words if name_tokens(w) or len(w) <= 2)


def search(name: str, birth_year: int | None = None, path: str = DB_PATH) -> list[dict]:
    """Listed entries whose name matches across scripts; birth year can veto."""
    tokens = sorted(name_tokens(name))[:MAX_QUERY_TOKENS]
    if len(tokens) < 2:
        return []
    if not source_status(path):
        raise IndexNotReady("sanctions index is not built yet (the worker builds it on first start)")
    # A match needs the shorter name fully inside the longer one, so every
    # candidate contains all tokens of some 2+ token subset of the query.
    # AND-queries keep common words ("ali", "muhammad") from flooding the
    # candidate list; subsets cover a listed name shorter than the query.
    # islice: the combinations are generated lazily and cut at 20 — building
    # the full list first explodes (26 tokens -> 67M lists -> out of memory).
    subsets = [tokens] + [list(c) for c in itertools.islice(
        (c for k in range(len(tokens) - 1, 1, -1) for c in itertools.combinations(tokens, k)),
        MAX_SUBSETS)]
    with _connect(path) as conn:
        rows = []
        try:
            for subset in subsets:
                rows += conn.execute(
                    "SELECT entity_id, name FROM name_fts WHERE name_fts MATCH ? LIMIT ?",
                    (" AND ".join(f'"{t}"' for t in subset), MAX_CANDIDATES),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            raise ToolError(f"sanctions index unreadable: {exc}") from exc
        query_words = _word_count(name)
        common_name = all(is_common_token(t) for t in tokens)
        best: dict[int, tuple[str, int]] = {}
        for row in rows:
            common = names_match(name, row["name"])
            # every word of the shorter name must be matched: "Kim Jong Un"
            # is not "Yo Jong KIM" even though "yo" folds away as too short
            if not common or len(common) < min(query_words, _word_count(row["name"])):
                continue
            if len(common) > best.get(row["entity_id"], ("", 0))[1]:
                best[row["entity_id"]] = (row["name"], len(common))
        hits = []
        for eid, (matched_name, _n) in best.items():
            e = conn.execute("SELECT * FROM entity WHERE id=?", (eid,)).fetchone()
            if e is None:
                continue
            years = json.loads(e["years"] or "[]")
            if birth_year and years and all(abs(birth_year - y) > 1 for y in years):
                continue   # a different birth year: not this person
            strength = "strong" if (birth_year and years) else "possible"
            hits.append({**dict(e), "matched_name": matched_name, "years": years,
                         "common_name": common_name,
                         "nationalities": json.loads(e["nationalities"] or "[]"),
                         "programs": json.loads(e["programs"] or "[]"), "strength": strength})
    hits.sort(key=lambda h: (h["strength"] != "strong", h["source"].startswith("pep")))
    return hits[:MAX_HITS]


def to_result(hit: dict) -> dict:
    """One index hit -> a result card that never claims identity."""
    is_pep = hit["source"].startswith("pep")
    label = "PEP (Wikidata)" if is_pep else SOURCES[hit["source"]]["label"]
    parts = [
        f"A {'public office holder' if is_pep else 'listed ' + hit['kind']} named "
        f"\"{hit['matched_name']}\" is on the {label}",
    ]
    if hit["note"]:
        parts.append(hit["note"])
    if hit["programs"] and not is_pep:
        parts.append("Programme: " + ", ".join(hit["programs"][:3]))
    if hit["years"]:
        parts.append("Listed birth year(s): " + ", ".join(str(y) for y in hit["years"]))
    if hit["nationalities"]:
        parts.append("Listed nationality: " + ", ".join(hit["nationalities"][:3]))
    if hit.get("common_name"):
        parts.append("Very common name: many unrelated people share it")
    parts.append("VERIFY: a name match is not proof of identity"
                 + ("" if hit["strength"] == "strong" else "; no birth year to compare"))
    return {
        "platform": label,
        "url": hit["url"],
        "status": "possible match",
        "source": "list_screening",
        "info": "; ".join(parts),
    }
