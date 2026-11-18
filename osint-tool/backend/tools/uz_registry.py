"""Uzbek official registers from the national open-data portal (data.egov.uz).

Replaces OpenCorporates for Uzbekistan with free, official data: the Tax
Committee legal-entity and VAT registers, the exchange's unscrupulous-supplier
register, Justice Ministry registers (NGOs, religious organisations, notaries,
legal consultancies, arbitration courts), state-owned enterprises, boards of
state companies and public-private-partnership partners.

The worker downloads each dataset's JSON export into one SQLite file with an
FTS5 index; searches go by STIR (tax id) or by organisation / person name.
Note: the portal itself truncates the two big tax registers at 65,535 rows,
so a company missing here may still exist.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time

import httpx

from services.names import fold, name_tokens, names_match
from tools.base import IndexNotReady, ToolError

DB_PATH = os.environ.get("UZ_REGISTRY_DB_PATH", "/app/data/uz_registry.db")
PORTAL = "https://data.egov.uz"
USER_AGENT = "osint-tool/1.0 (self-hosted research; open-data sync)"
TRUNCATED_AT = 65535
MAX_HITS = 15
MAX_PARTIAL = 8

# key: (dataset id, label, columns). Column roles: name, stir, person, role,
# region (list), extra (list), flag (a warning shown with every hit).
DATASETS = {
    "tax_entities": {"id": "610a74471a64fdd0373a8e20", "label": "Tax Committee: legal-entity register",
                     "name": "Korxonanomi", "stir": "STIR", "region": ["Viloyat", "Tuman"]},
    "vat_payers": {"id": "610a7a901a64fdd0373a8e3a", "label": "Tax Committee: VAT payers register",
                   "name": "Korxonanomi", "stir": "STIR", "region": ["Hudud"],
                   "extra": ["QQSgaotishsanasi", "Holati"]},
    "unscrupulous_suppliers": {"id": "6111120adb32b99538e0822a",
                               "label": "UzEx: register of unscrupulous suppliers",
                               "name": "Tashkilot", "stir": "STIR", "region": ["Hudud"],
                               "extra": ["KiritilganSana", "ChiqarilishSanasi"],
                               "flag": "listed as an unscrupulous supplier in public procurement"},
    "brokers": {"id": "61111019db32b99538e08218", "label": "UzEx: brokerage offices",
                "name": "Brokerlik idorasining nomi", "region": ["Hudud"]},
    "trading_floors": {"id": "61111064db32b99538e0821c", "label": "UzEx: trading floors",
                       "name": "Yuridik shaxs nomi", "region": ["Savdo maydonchasining hududi"]},
    "ngos": {"id": "6107d53e2a2e256d868e8702", "label": "Justice Ministry: NGO register",
             "name": "Nomi", "region": ["hudud"], "extra": ["shakli", "Manzili"]},
    "religious": {"id": "6107d5b52a2e256d868e8706", "label": "Justice Ministry: religious organisations",
                  "name": "nomi", "extra": ["Konfessiyasi", "adress"]},
    "notaries": {"id": "6107d4862a2e256d868e86fc", "label": "Justice Ministry: notary offices",
                 "person": "Notariusning familiyasi, ismi va otasining ismi", "role": "notary",
                 "region": ["Hudud nomi", "Faoliyat yuritish hududi"],
                 "extra": ["Notarial idoraning joylashgan manzili"]},
    "legal_consulting": {"id": "6107d3532a2e256d868e86f0",
                         "label": "Justice Ministry: legal consultancy firms",
                         "name": "tashkilotnomi", "person": "fio", "role": "head of a legal consultancy",
                         "region": ["Hudud"], "extra": ["Reestrdanchiqarish"]},
    "arbitration": {"id": "6107d5772a2e256d868e8704", "label": "Justice Ministry: arbitration courts",
                    "name": "nomi", "person": "FIO", "role": "chair of an arbitration court",
                    "region": ["region"]},
    "extremist_orgs": {"id": "6107d0f52a2e256d868e86d6",
                       "label": "Justice Ministry: organisations recognised as extremist",
                       "name": "Nomi", "flag": "on the official list of organisations recognised as extremist"},
    "soe_national": {"id": "6110bec8db32b99538e08167", "label": "State-owned enterprises (national list)"},
    "soe_karakalpakstan": {"id": "637ef75f4878653e5fe42cd2", "label": "State-owned enterprises: Karakalpakstan",
                           "name": "TASHKILOTNOMI", "stir": "STIR", "region": ["HUDUD", "SHAHARTUMAN"],
                           "extra": ["TASHKILOTHOLATI", "DAVLATULUSHI", "YUQORITURUVCHITASHKILOT"]},
    "soe_khorezm": {"id": "637ef7a84878653e5fe42cd6", "label": "State-owned enterprises: Khorezm",
                    "name": "TASHKILOTNOMI", "stir": "STIR", "region": ["HUDUD", "SHAHARTUMAN"],
                    "extra": ["TASHKILOTHOLATI", "DAVLATULUSHI", "YUQORITURUVCHITASHKILOT"]},
    "soe_bukhara": {"id": "637ef88d4878653e5fe42cda", "label": "State-owned enterprises: Bukhara",
                    "name": "TASHKILOTNOMI", "stir": "STIR", "region": ["HUDUD", "SHAHARTUMAN"],
                    "extra": ["TASHKILOTHOLATI", "DAVLATULUSHI", "YUQORITURUVCHITASHKILOT"]},
    "soe_navoi": {"id": "637ef8d14878653e5fe42ce0", "label": "State-owned enterprises: Navoi",
                  "name": "TASHKILOTNOMI", "stir": "STIR", "region": ["HUDUD", "SHAHARTUMAN"],
                  "extra": ["TASHKILOTHOLATI", "DAVLATULUSHI", "YUQORITURUVCHITASHKILOT"]},
    "soe_board_nominees": {"id": "64dc9758b04a41cb2e29d572",
                           "label": "Ministry of Economy and Finance: nominees in state companies",
                           "name": "Korxonalarnomi", "person": "AmaldaginomzodlarFISh",
                           "role_col": "AmaldaginomzodlarLavozim"},
    "soe_boards": {"id": "64dc9789b04a41cb2e29d575",
                   "label": "Ministry of Economy and Finance: supervisory boards of state companies",
                   "name": "Korxonanomi", "person": "FISh", "role_col": "Lavozimi"},
    "ppp_partners": {"id": "64dc9c7fb04a41cb2e29d597", "label": "Public-private partnership project register",
                     "name": "Xususiysherik", "extra": ["Loyihanomi", "Davlatsherigi", "Loyihaqiymati",
                                                        "Loyiharoyxatgaolingansana"]},
}

# Legal-form words that say nothing about which company it is.
_LEGAL_FORMS = {
    "mchj", "ooo", "mas", "masuliyati", "cheklangan", "jamiyati", "jamiyat", "aj", "aksiyadorlik",
    "ao", "oao", "zao", "pao", "llc", "ltd", "jsc", "inc", "xk", "xususiy", "korxonasi", "korxona",
    "dk", "duk", "uk", "fx", "fermer", "xojaligi", "yatt", "ip", "ooo", "tashkiloti", "filiali",
    "ооо", "мчж", "аж", "ао", "оао", "зао", "пао", "хк", "хусусий", "корхонаси", "фх", "дук", "унитар",
}
# compared after the same folding the tokens get (MCHJ -> "mkhj", ООО -> "o")
_LEGAL_FORMS_FOLDED = {fold(word) for word in _LEGAL_FORMS}
_STIR_RE = re.compile(r"^\d{9}$")


def org_tokens(name: str) -> list[str]:
    """Distinctive tokens of an organisation name (legal forms dropped)."""
    out = []
    for word in re.split(r"[\s,.\"“”«»'’`()/\-_]+", str(name or "")):
        key = fold(word)
        if len(key) >= 2 and key not in _LEGAL_FORMS_FOLDED and key not in out:
            out.append(key)
    return out


def _auto_columns(sample: dict) -> dict:
    """Guess roles for a dataset without a hand-written mapping."""
    spec = {}
    for col in sample:
        low = col.lower()
        if "stir" in low or low in ("inn", "tin"):
            spec.setdefault("stir", col)
        elif any(k in low for k in ("nomi", "nom", "tashkilot", "korxona")) and "manzil" not in low:
            spec.setdefault("name", col)
        elif any(k in low for k in ("hudud", "viloyat", "tuman")):
            spec.setdefault("region", []).append(col)
    return spec


def rows_to_records(key: str, rows: list[dict]) -> list[dict]:
    spec = dict(DATASETS[key])
    if rows and "name" not in spec and "person" not in spec:
        spec.update(_auto_columns(rows[0]))
    records = []
    for row in rows:
        def val(col):
            return " ".join(str(row.get(col) or "").split()) if col else ""
        name, person = val(spec.get("name")), val(spec.get("person"))
        if not name and not person:
            continue
        stir = re.sub(r"\D", "", val(spec.get("stir")))
        records.append({
            "name": name[:400], "stir": stir if _STIR_RE.match(stir) else "",
            "person": person[:200], "role": val(spec.get("role_col")) or spec.get("role", ""),
            "region": ", ".join(v for v in (val(c) for c in spec.get("region", [])) if v),
            "extra": {c: val(c) for c in spec.get("extra", []) if val(c)},
        })
    return records


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
CREATE TABLE IF NOT EXISTS dataset (key TEXT PRIMARY KEY, fetched_at REAL, rows INTEGER, truncated INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS record (id INTEGER PRIMARY KEY, dataset TEXT, name TEXT, stir TEXT,
  person TEXT, role TEXT, region TEXT, extra TEXT);
CREATE INDEX IF NOT EXISTS record_stir ON record(stir);
CREATE INDEX IF NOT EXISTS record_dataset ON record(dataset);
CREATE VIRTUAL TABLE IF NOT EXISTS record_fts USING fts5(org, person, record_id UNINDEXED);
""")


def store_dataset(key: str, records: list[dict], truncated: bool, path: str = DB_PATH) -> int:
    init_db(path)
    with _connect(path) as conn:
        old = [r[0] for r in conn.execute("SELECT id FROM record WHERE dataset=?", (key,))]
        if old:
            for i in range(0, len(old), 900):
                chunk = old[i:i + 900]
                conn.execute(f"DELETE FROM record_fts WHERE record_id IN ({','.join('?' * len(chunk))})", chunk)
            conn.execute("DELETE FROM record WHERE dataset=?", (key,))
        for r in records:
            cur = conn.execute(
                "INSERT INTO record (dataset, name, stir, person, role, region, extra) VALUES (?,?,?,?,?,?,?)",
                (key, r["name"], r["stir"], r["person"], r["role"], r["region"], json.dumps(r["extra"], ensure_ascii=False)),
            )
            conn.execute("INSERT INTO record_fts (org, person, record_id) VALUES (?,?,?)",
                         (" ".join(org_tokens(r["name"])), " ".join(sorted(name_tokens(r["person"]))), cur.lastrowid))
        conn.execute("INSERT OR REPLACE INTO dataset VALUES (?,?,?,?,?)",
                     (key, time.time(), len(records), int(truncated), "ok"))
    return len(records)


def dataset_status(path: str = DB_PATH) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    with _connect(path) as conn:
        try:
            return {r["key"]: dict(r) for r in conn.execute("SELECT * FROM dataset")}
        except sqlite3.OperationalError:
            return {}


async def refresh(path: str = DB_PATH) -> dict:
    """Weekly: re-download every register from the open-data portal."""
    init_db(path)
    report = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=20.0),
                                 headers={"User-Agent": USER_AGENT}) as client:
        for key, spec in DATASETS.items():
            try:
                response = await client.get(f"{PORTAL}/apiData/MainData/GetByFile",
                                            params={"id": spec["id"], "fileType": 1, "tableType": 2})
                if response.status_code != 200:
                    raise ToolError(f"HTTP {response.status_code}")
                rows = response.json()
                if not isinstance(rows, list):
                    raise ToolError("unexpected JSON")
                records = await asyncio.to_thread(rows_to_records, key, rows)
                if not records:
                    raise ToolError("no usable rows (empty or format changed)")
                count = await asyncio.to_thread(store_dataset, key, records, len(rows) >= TRUNCATED_AT, path)
                report[key] = f"{count} records" + (" (portal truncated)" if len(rows) >= TRUNCATED_AT else "")
            except Exception as exc:  # noqa: BLE001 - keep the previous copy
                report[key] = f"error: {type(exc).__name__}: {exc}"[:160]
            await asyncio.sleep(0.5)
    return report


# ---------------- search ----------------

def _rows(conn, sql, args):
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def search_org(query: str, path: str = DB_PATH) -> list[dict]:
    """By STIR (exact) or by organisation name (every distinctive token)."""
    if not dataset_status(path):
        raise IndexNotReady("Uzbek register index is not built yet (the worker builds it on first start)")
    query = str(query or "").strip()
    with _connect(path) as conn:
        digits = re.sub(r"\D", "", query)
        if _STIR_RE.match(digits):
            rows = _rows(conn, "SELECT * FROM record WHERE stir=? LIMIT ?", (digits, MAX_HITS * 2))
        else:
            tokens = org_tokens(query)
            if not tokens:
                return []
            match = "org : (" + " AND ".join(f'"{t}"' for t in tokens) + ")"
            rows = _rows(conn, "SELECT record.* FROM record_fts JOIN record ON record.id = record_fts.record_id "
                               "WHERE record_fts MATCH ? LIMIT ?", (match, MAX_HITS * 4))
    hits = [dict(r) for r in rows]
    if not _STIR_RE.match(re.sub(r"\D", "", query)):
        wanted = set(org_tokens(query))
        for hit in hits:
            # exact: every distinctive word of the registered name is in the
            # query ("Hamkorbank" for "Hamkorbank ATB"); partial: the query is
            # only part of a longer name ("Apple" inside "Apple Savdo")
            have = set(org_tokens(hit["name"]))
            hit["match"] = "exact" if have and have <= wanted else "partial"
        exact = [h for h in hits if h["match"] == "exact"]
        partial = [h for h in hits if h["match"] == "partial"][:MAX_PARTIAL]
        hits = exact + partial
    else:
        for hit in hits:
            hit["match"] = "exact"
    return hits[:MAX_HITS * 2]


def search_person(name: str, path: str = DB_PATH) -> list[dict]:
    """People listed with a role in an official register (board member, notary...)."""
    tokens = sorted(name_tokens(name))[:6]
    if len(tokens) < 2:
        return []
    if not dataset_status(path):
        raise IndexNotReady("Uzbek register index is not built yet (the worker builds it on first start)")
    with _connect(path) as conn:
        match = "person : (" + " AND ".join(f'"{t}"' for t in tokens) + ")"
        rows = _rows(conn, "SELECT record.* FROM record_fts JOIN record ON record.id = record_fts.record_id "
                           "WHERE record_fts MATCH ? LIMIT ?", (match, MAX_HITS * 4))
    return [dict(r) for r in rows if names_match(name, r["person"])][:MAX_HITS]


def to_result(record: dict, as_person: bool = False) -> dict:
    spec = DATASETS.get(record["dataset"], {})
    parts = []
    if as_person and record.get("person"):
        parts.append(f"Person: {record['person']}" + (f" ({record['role']})" if record.get("role") else ""))
    if record.get("name"):
        parts.append(f"Organisation: {record['name']}")
    if not as_person and record.get("person"):
        # a company search lists the people the register names (board, head)
        parts.append(f"Listed person: {record['person']}"
                     + (f" ({record['role']})" if record.get("role") else ""))
    if record.get("stir"):
        parts.append(f"STIR: {record['stir']}")
    if record.get("region"):
        parts.append(f"Region: {record['region']}")
    for col, value in json.loads(record.get("extra") or "{}").items():
        parts.append(f"{col}: {value[:160]}")
    if spec.get("flag"):
        parts.append("WARNING: " + spec["flag"])
    if as_person:
        parts.append("A same-name entry in an official register; confirm it is the same person")
    return {
        "platform": f"UZ register — {spec.get('label', record['dataset'])}",
        "url": f"{PORTAL}/data/{spec.get('id', '')}",
        "status": "warning" if spec.get("flag") else "found",
        "source": "uz_register",
        "info": "; ".join(parts),
    }
