"""DNS history without SecurityTrails: what did a domain point to before?

Three free sources, merged into one table:
- our own observations: every domain investigation stores the records it
  resolved, with first/last seen dates, so history accumulates over time;
- Mnemonic passive DNS (no key; 10 requests/min, 1000/day, TLP:WHITE data);
- Robtex free API (no key; 10 requests/hour per IP — strictly budgeted).
External answers are cached for 7 days per domain, and calls are spaced to
stay well inside each service's published limits.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from collections import deque

import httpx

DB_PATH = os.environ.get("PDNS_DB_PATH", "/app/data/pdns.db")
USER_AGENT = "osint-tool/1.0 (self-hosted research; low volume)"
TIMEOUT = httpx.Timeout(15.0)
EXTERNAL_TTL_SECONDS = 7 * 24 * 3600
MNEMONIC_INTERVAL = 6.5          # <= 10 per minute
ROBTEX_PER_HOUR = 8              # their limit is 10/hour; keep a margin
RRTYPES = {"A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA", "CAA"}
MAX_SHOWN = 25

_mnemonic_lock = asyncio.Lock()
_mnemonic_last = 0.0
_robtex_calls: deque = deque()
_robtex_lock = asyncio.Lock()


def _connect(path: str = DB_PATH) -> sqlite3.Connection:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
CREATE TABLE IF NOT EXISTS observation (
  domain TEXT, rrtype TEXT, value TEXT, source TEXT,
  first_seen REAL, last_seen REAL, seen_count INTEGER,
  PRIMARY KEY (domain, rrtype, value, source));
CREATE TABLE IF NOT EXISTS fetched (domain TEXT, source TEXT, at REAL, PRIMARY KEY (domain, source));
""")
    return conn


def upsert(domain: str, rows: list[tuple[str, str, float, float, int]], source: str,
           path: str = DB_PATH) -> int:
    """rows: (rrtype, value, first_seen, last_seen, count). Widens date ranges."""
    domain = domain.lower().rstrip(".")
    with _connect(path) as conn:
        for rrtype, value, first, last, count in rows:
            rrtype = rrtype.upper()
            if rrtype not in RRTYPES or not value:
                continue
            conn.execute(
                "INSERT INTO observation VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(domain, rrtype, value, source) DO UPDATE SET "
                "first_seen=MIN(first_seen, excluded.first_seen), "
                "last_seen=MAX(last_seen, excluded.last_seen), "
                "seen_count=MAX(seen_count, excluded.seen_count)",
                (domain, rrtype, str(value).rstrip(".")[:255], source, first, last, count),
            )
    return len(rows)


def record_self(domain: str, records: list[tuple[str, list[str]]], path: str = DB_PATH) -> None:
    """Store what our own resolver saw just now."""
    now = time.time()
    rows = [(rrtype, value, now, now, 1) for rrtype, values in records for value in values]
    with _connect(path) as conn:
        for rrtype, value, *_ in rows:
            conn.execute(
                "UPDATE observation SET seen_count = seen_count + 1 WHERE domain=? AND rrtype=? "
                "AND value=? AND source='self'", (domain.lower(), rrtype, str(value).rstrip(".")[:255]))
    upsert(domain, rows, "self", path)


def wipe(path: str | None = None) -> int:
    """Full deletion (8b.6): every domain in this store was one somebody searched."""
    path = path or DB_PATH
    if not os.path.exists(path):
        return 0
    with _connect(path) as conn:
        removed = conn.execute("DELETE FROM observation").rowcount
        conn.execute("DELETE FROM fetched")
    with _connect(path) as conn:
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return removed


def _fresh(domain: str, source: str, path: str) -> bool:
    with _connect(path) as conn:
        row = conn.execute("SELECT at FROM fetched WHERE domain=? AND source=?", (domain, source)).fetchone()
    return bool(row) and time.time() - row["at"] < EXTERNAL_TTL_SECONDS


def _mark_fetched(domain: str, source: str, path: str) -> None:
    with _connect(path) as conn:
        conn.execute("INSERT OR REPLACE INTO fetched VALUES (?,?,?)", (domain, source, time.time()))


def parse_mnemonic(payload: dict) -> list[tuple]:
    rows = []
    for item in (payload or {}).get("data") or []:
        try:
            rows.append((item["rrtype"], item["answer"], item["firstSeenTimestamp"] / 1000,
                         item["lastSeenTimestamp"] / 1000, int(item.get("times") or 1)))
        except (KeyError, TypeError):
            continue
    return rows


def parse_robtex(text: str) -> list[tuple]:
    rows = []
    for line in (text or "").splitlines():
        try:
            item = json.loads(line)
            rows.append((item["rrtype"], item["rrdata"], float(item["time_first"]),
                         float(item["time_last"]), int(item.get("count") or 1)))
        except (ValueError, KeyError, TypeError):
            continue
    return rows


async def _mnemonic(client: httpx.AsyncClient, domain: str) -> list[tuple]:
    global _mnemonic_last
    async with _mnemonic_lock:
        wait = _mnemonic_last + MNEMONIC_INTERVAL - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _mnemonic_last = time.monotonic()
        response = await client.get(f"https://api.mnemonic.no/pdns/v3/{domain}", params={"limit": 100})
    if response.status_code != 200:
        raise RuntimeError(f"Mnemonic HTTP {response.status_code}")
    return parse_mnemonic(response.json())


async def _robtex(client: httpx.AsyncClient, domain: str) -> list[tuple] | None:
    async with _robtex_lock:
        now = time.monotonic()
        while _robtex_calls and now - _robtex_calls[0] > 3600:
            _robtex_calls.popleft()
        if len(_robtex_calls) >= ROBTEX_PER_HOUR:
            return None            # hourly budget used: skip, try again later
        _robtex_calls.append(now)
    response = await client.get(f"https://freeapi.robtex.com/pdns/forward/{domain}")
    if response.status_code != 200:
        raise RuntimeError(f"Robtex HTTP {response.status_code}")
    return parse_robtex(response.text)


async def refresh_external(domain: str, path: str = DB_PATH) -> list[str]:
    """Pull Mnemonic and Robtex history unless fetched within 7 days."""
    domain = domain.lower().rstrip(".")
    notes = []
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        for source, fetch in (("mnemonic", _mnemonic), ("robtex", _robtex)):
            if await asyncio.to_thread(_fresh, domain, source, path):
                continue
            try:
                rows = await fetch(client, domain)
            except (httpx.HTTPError, RuntimeError) as exc:
                notes.append(f"{source}: {exc}")
                continue
            if rows is None:
                notes.append(f"{source}: hourly limit reached, history from it later")
                continue
            await asyncio.to_thread(upsert, domain, rows, source, path)
            await asyncio.to_thread(_mark_fetched, domain, source, path)
    return notes


def history(domain: str, path: str = DB_PATH) -> list[dict]:
    """All observations, one row per (rrtype, value), sources merged."""
    if not os.path.exists(path):
        return []
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT rrtype, value, MIN(first_seen) AS first, MAX(last_seen) AS last, "
            "GROUP_CONCAT(DISTINCT source) AS sources FROM observation WHERE domain=? "
            "GROUP BY rrtype, value ORDER BY rrtype, last DESC", (domain.lower().rstrip("."),)).fetchall()
    return [dict(r) for r in rows]


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


async def lookup(domain: str, path: str = DB_PATH) -> tuple[dict | None, list[str]]:
    """Refresh external history if stale, then summarise everything we know."""
    notes = await refresh_external(domain, path)
    rows = await asyncio.to_thread(history, domain, path)
    if not rows:
        return None, notes
    now = time.time()
    current = [r for r in rows if now - r["last"] < 30 * 86400]
    past = [r for r in rows if now - r["last"] >= 30 * 86400]
    lines = []
    for r in (past + current)[:MAX_SHOWN]:
        lines.append(f"{r['rrtype']} {r['value']} ({_day(r['first'])} → {_day(r['last'])}; {r['sources']})")
    span_from = _day(min(r["first"] for r in rows))
    entry = {
        "platform": "DNS history",
        "url": f"https://www.robtex.com/dns-lookup/{domain}",
        "status": "found",
        "info": (f"{len(rows)} record(s) seen since {span_from}; {len(past)} no longer current. "
                 + " | ".join(lines)),
        "source": "passive_dns",
    }
    return entry, notes
