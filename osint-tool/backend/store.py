"""Durable case storage (SQLite). A case groups findings from many searches,
each kept with its source result and timestamp (provenance)."""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

DB_PATH = os.environ.get("CASES_DB_PATH", "/app/data/cases.db")
MAX_NAME = 120


class CaseError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cases ("
            "id TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS findings ("
            "id TEXT PRIMARY KEY, case_id TEXT NOT NULL, category TEXT NOT NULL, "
            "query TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL, "
            "FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_findings_case ON findings(case_id)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS watches ("
            "id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, "
            "query TEXT NOT NULL, interval_minutes INTEGER NOT NULL, "
            "active INTEGER NOT NULL DEFAULT 1, last_hash TEXT, "
            "last_status TEXT, last_checked_at TEXT, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS watch_events ("
            "id TEXT PRIMARY KEY, watch_id TEXT NOT NULL, summary TEXT NOT NULL, "
            "created_at TEXT NOT NULL, "
            "FOREIGN KEY(watch_id) REFERENCES watches(id) ON DELETE CASCADE)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_watch ON watch_events(watch_id)"
        )


def create_case(name: str) -> dict:
    name = " ".join((name or "").split())
    if not (1 <= len(name) <= MAX_NAME):
        raise CaseError(f"Case name must be 1-{MAX_NAME} characters.")
    case_id = uuid.uuid4().hex
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO cases (id, name, created_at, updated_at) VALUES (?,?,?,?)",
            (case_id, name, now, now),
        )
    return {"id": case_id, "name": name, "created_at": now, "updated_at": now}


def list_cases() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT c.id, c.name, c.created_at, c.updated_at, "
            "COUNT(f.id) AS findings "
            "FROM cases c LEFT JOIN findings f ON f.case_id = c.id "
            "GROUP BY c.id ORDER BY c.updated_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_case(case_id: str) -> dict:
    with _connect() as conn:
        case = conn.execute(
            "SELECT id, name, created_at, updated_at FROM cases WHERE id=?",
            (case_id,),
        ).fetchone()
        if case is None:
            raise CaseError("Case not found.")
        findings = conn.execute(
            "SELECT id, category, query, result, created_at FROM findings "
            "WHERE case_id=? ORDER BY created_at",
            (case_id,),
        ).fetchall()
    return {
        "case": dict(case),
        "findings": [
            {
                "id": row["id"],
                "category": row["category"],
                "query": row["query"],
                "created_at": row["created_at"],
                "result": json.loads(row["result"]),
            }
            for row in findings
        ],
    }


def add_finding(case_id: str, category: str, query: str, result: dict) -> dict:
    now = _now()
    finding_id = uuid.uuid4().hex
    with _connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM cases WHERE id=?", (case_id,)
        ).fetchone()
        if exists is None:
            raise CaseError("Case not found.")
        conn.execute(
            "INSERT INTO findings (id, case_id, category, query, result, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (finding_id, case_id, category, query, json.dumps(result), now),
        )
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (now, case_id))
    return {"id": finding_id, "created_at": now}


def delete_case(case_id: str) -> None:
    with _connect() as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM findings WHERE case_id=?", (case_id,))
        cur = conn.execute("DELETE FROM cases WHERE id=?", (case_id,))
        if cur.rowcount == 0:
            raise CaseError("Case not found.")


def delete_finding(case_id: str, finding_id: str) -> None:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM findings WHERE id=? AND case_id=?", (finding_id, case_id)
        )
        if cur.rowcount == 0:
            raise CaseError("Finding not found.")
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (_now(), case_id))


# ---- Watches (scheduled re-scans) ----

MIN_INTERVAL = 5
MAX_INTERVAL = 7 * 24 * 60  # a week


def create_watch(name: str, category: str, query: str,
                 interval_minutes: int) -> dict:
    name = " ".join((name or "").split())
    if not (1 <= len(name) <= MAX_NAME):
        raise CaseError(f"Watch name must be 1-{MAX_NAME} characters.")
    category = (category or "").strip()
    query = (query or "").strip()
    if not category or not query:
        raise CaseError("Watch needs a category and a query.")
    try:
        interval_minutes = int(interval_minutes)
    except (TypeError, ValueError):
        raise CaseError("Interval must be a whole number of minutes.")
    if not (MIN_INTERVAL <= interval_minutes <= MAX_INTERVAL):
        raise CaseError(
            f"Interval must be {MIN_INTERVAL}-{MAX_INTERVAL} minutes."
        )
    watch_id = uuid.uuid4().hex
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO watches (id, name, category, query, interval_minutes, "
            "active, last_hash, last_status, last_checked_at, created_at) "
            "VALUES (?,?,?,?,?,1,NULL,NULL,NULL,?)",
            (watch_id, name, category, query, interval_minutes, now),
        )
    return get_watch(watch_id)


def _watch_row(conn, watch_id: str):
    row = conn.execute(
        "SELECT id, name, category, query, interval_minutes, active, "
        "last_hash, last_status, last_checked_at, created_at "
        "FROM watches WHERE id=?", (watch_id,)
    ).fetchone()
    if row is None:
        raise CaseError("Watch not found.")
    return row


def get_watch(watch_id: str, event_limit: int = 20) -> dict:
    with _connect() as conn:
        row = _watch_row(conn, watch_id)
        events = conn.execute(
            "SELECT id, summary, created_at FROM watch_events "
            "WHERE watch_id=? ORDER BY created_at DESC LIMIT ?",
            (watch_id, event_limit),
        ).fetchall()
    watch = dict(row)
    watch["active"] = bool(watch["active"])
    watch["events"] = [dict(e) for e in events]
    return watch


def list_watches() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT w.id, w.name, w.category, w.query, w.interval_minutes, "
            "w.active, w.last_status, w.last_checked_at, w.created_at, "
            "COUNT(e.id) AS event_count, MAX(e.created_at) AS last_event_at "
            "FROM watches w LEFT JOIN watch_events e ON e.watch_id = w.id "
            "GROUP BY w.id ORDER BY w.created_at DESC"
        ).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["active"] = bool(d["active"])
        out.append(d)
    return out


def delete_watch(watch_id: str) -> None:
    with _connect() as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM watch_events WHERE watch_id=?", (watch_id,))
        cur = conn.execute("DELETE FROM watches WHERE id=?", (watch_id,))
        if cur.rowcount == 0:
            raise CaseError("Watch not found.")


def set_watch_active(watch_id: str, active: bool) -> dict:
    with _connect() as conn:
        _watch_row(conn, watch_id)
        conn.execute(
            "UPDATE watches SET active=? WHERE id=?",
            (1 if active else 0, watch_id),
        )
    return get_watch(watch_id)


def due_watches() -> list[dict]:
    """Active watches whose interval has elapsed since the last check."""
    now = datetime.now(timezone.utc)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, category, query, interval_minutes, last_hash, "
            "last_checked_at FROM watches WHERE active=1"
        ).fetchall()
    due = []
    for row in rows:
        last = row["last_checked_at"]
        if last is None:
            due.append(dict(row))
            continue
        try:
            elapsed = (now - datetime.fromisoformat(last)).total_seconds() / 60
        except ValueError:
            elapsed = row["interval_minutes"]
        if elapsed >= row["interval_minutes"]:
            due.append(dict(row))
    return due


def record_watch_check(watch_id: str, new_hash: str, status: str,
                       change_summary: str | None) -> None:
    """Persist the outcome of one check; log an event only on a real change."""
    now = _now()
    with _connect() as conn:
        conn.execute(
            "UPDATE watches SET last_hash=?, last_status=?, last_checked_at=? "
            "WHERE id=?", (new_hash, status, now, watch_id),
        )
        if change_summary:
            conn.execute(
                "INSERT INTO watch_events (id, watch_id, summary, created_at) "
                "VALUES (?,?,?,?)",
                (uuid.uuid4().hex, watch_id, change_summary, now),
            )
