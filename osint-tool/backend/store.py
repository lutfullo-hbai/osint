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
