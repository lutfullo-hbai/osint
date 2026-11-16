"""Our own copy of Maigret's site database, kept healthy and Uzbek-aware.

- Built from the database bundled with the installed Maigret package.
- Uzbek sites (".uz" or tag "uz") are promoted into the default scan: Maigret
  only scans its top ~500 sites by Alexa rank, and none of them made the cut.
- Extra site definitions can be added in assets/maigret_extra_sites.json.
- A weekly self-check (`maigret --self-check --auto-disable`) turns off sites
  whose detection no longer works, so they stop producing false hits.
The copy lives on the data volume; the package file is never modified.
"""
from __future__ import annotations

import json
import os
import tempfile

from tools.base import ToolError, run_command, shorten

DB_PATH = os.environ.get("MAIGRET_DB_PATH", "/app/data/maigret_db.json")
EXTRA_SITES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "assets", "maigret_extra_sites.json"
)
PROMOTED_RANK = 400          # inside the default top-500 scan window
SELF_CHECK_TOP_SITES = 600   # what we actually scan, plus some margin
SELF_CHECK_TIMEOUT_SECONDS = 1800


def bundled_db_path() -> str:
    import maigret
    return os.path.join(os.path.dirname(maigret.__file__), "resources", "data.json")


def is_uzbek(site: dict) -> bool:
    url = f"{site.get('urlMain') or ''} {site.get('url') or ''}"
    return "uz" in (site.get("tags") or []) or ".uz/" in url or url.rstrip("/").endswith(".uz")


def customize(db: dict, extra_sites: dict | None = None) -> tuple[dict, list[str]]:
    """Merge extra definitions and promote Uzbek sites. Returns (db, promoted)."""
    sites = db.setdefault("sites", {})
    for name, definition in (extra_sites or {}).items():
        sites[name] = definition
    promoted = []
    for name, site in sites.items():
        if is_uzbek(site) and not site.get("disabled"):
            rank = site.get("alexaRank")
            if not isinstance(rank, int) or rank > PROMOTED_RANK:
                site["alexaRank"] = PROMOTED_RANK
            promoted.append(name)
    return db, sorted(promoted)


def _write_atomic(path: str, data: dict) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


def _load_extra() -> dict:
    try:
        with open(EXTRA_SITES_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("sites", {}) if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def build_db(path: str = DB_PATH) -> list[str]:
    """(Re)create our database from the bundled one. Returns promoted sites."""
    with open(bundled_db_path(), encoding="utf-8") as fh:
        db = json.load(fh)
    db, promoted = customize(db, _load_extra())
    _write_atomic(path, db)
    return promoted


def ensure_db(path: str = DB_PATH) -> str | None:
    """Path of a usable custom database, building it on first use."""
    if not os.path.exists(path):
        try:
            build_db(path)
        except (OSError, ValueError, ImportError):
            return None
    return path


def disabled_count(path: str = DB_PATH) -> int:
    with open(path, encoding="utf-8") as fh:
        return sum(1 for s in json.load(fh).get("sites", {}).values() if s.get("disabled"))


async def run_self_check(path: str = DB_PATH) -> dict:
    """Rebuild from the package, then let Maigret disable broken sites."""
    promoted = build_db(path)
    before = disabled_count(path)
    execution = await run_command(
        [
            "maigret", "--db", path, "--self-check", "--auto-disable",
            "--top-sites", str(SELF_CHECK_TOP_SITES), "--no-color", "--no-autoupdate",
        ],
        timeout=SELF_CHECK_TIMEOUT_SECONDS,
        input_text="y\n",   # "save changes permanently?" -> yes (to our copy)
    )
    if execution["returncode"] != 0 and "successfully updated" not in execution["stdout"]:
        raise ToolError(f"Maigret self-check failed: {shorten(execution['stderr'] or execution['stdout'])}")
    after = disabled_count(path)
    return {"promoted": len(promoted), "newly_disabled": after - before, "disabled_total": after}
