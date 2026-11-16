"""Holehe, run in-process: which sites say "this email is already registered".

Every Holehe module asks one site's sign-up (or similar) form whether an
address is taken. That is a *registration signal*, not a published fact, so
results are labelled unconfirmed and are never identity evidence on their own.

Safety rules (ROADMAP red lines):
- modules that drive a password-recovery flow are never run: they can send
  the address owner a reset email or SMS;
- modules that submit a login form are off by default: failed-login alerts
  and lockouts reach the owner too (HOLEHE_ALLOW_LOGIN=1 to opt in);
- adult-site registrations are special-category personal data and are not
  checked (HOLEHE_INCLUDE_ADULT=1 to opt in).

Each module ends in one of three states: used / not_used / unknown (rate
limit, captcha, error). Module health is remembered: a module that only ever
answers "unknown" is paused, and one that claims a random never-used address
is registered (daily canary) is paused as broken.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import pkgutil
import re
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache

import httpx

from cache import get_client
from tools.base import ToolError, positional_arg

MODULE_TIMEOUT_SECONDS = 12
CONCURRENCY = 20
MIN_INTERVAL_PER_SITE_SECONDS = 2.0   # across overlapping runs, per site
HEALTH_KEY = "holehe:health"
HEALTH_WINDOW = 20
UNKNOWN_PAUSE_AFTER = 10              # all-unknown answers before a pause
UNKNOWN_PAUSE_SECONDS = 24 * 3600
FALSE_POSITIVE_PAUSE_SECONDS = 7 * 24 * 3600

NEVER_RUN_METHODS = {"password recovery"}
OPT_IN_METHODS = {"login": "HOLEHE_ALLOW_LOGIN"}
OPT_IN_CATEGORIES = {"porn": "HOLEHE_INCLUDE_ADULT"}

SIGNAL_INFO = (
    "Registration signal (unconfirmed): this site's sign-up check reports the "
    "address as taken. It does not show a profile or who owns it."
)


@dataclass(frozen=True)
class HoleheModule:
    name: str
    category: str
    method: str
    func: object


@lru_cache(maxsize=1)
def available_modules() -> tuple[HoleheModule, ...]:
    """Every Holehe module with its category and declared method."""
    import holehe.modules as root

    found = []
    for info in pkgutil.walk_packages(root.__path__, root.__name__ + "."):
        if info.ispkg:
            continue
        module = importlib.import_module(info.name)
        name = info.name.rsplit(".", 1)[-1]
        func = getattr(module, name, None)
        if not callable(func):
            continue
        try:
            with open(module.__file__, encoding="utf-8") as fh:
                source = fh.read()
        except OSError:
            source = ""
        match = re.search(r"^\s*method\s*=\s*['\"]([^'\"]+)", source, re.M)
        category = info.name.split(".")[-2]
        found.append(HoleheModule(name, category, match.group(1) if match else "unknown", func))
    return tuple(sorted(found, key=lambda m: m.name))


def _opted_in(env: str) -> bool:
    return os.environ.get(env, "").strip() in ("1", "true", "yes")


def policy_allows(module: HoleheModule) -> bool:
    if module.method in NEVER_RUN_METHODS:
        return False
    if module.method in OPT_IN_METHODS and not _opted_in(OPT_IN_METHODS[module.method]):
        return False
    if module.category in OPT_IN_CATEGORIES and not _opted_in(OPT_IN_CATEGORIES[module.category]):
        return False
    return True


# ---- module health (Redis when available, process memory otherwise) ----

_memory_health: dict[str, dict] = {}


async def load_health() -> dict[str, dict]:
    client = await get_client()
    if client is None:
        return {k: dict(v) for k, v in _memory_health.items()}
    try:
        raw = await client.hgetall(HEALTH_KEY)
    except Exception:  # noqa: BLE001 - health is advisory
        return {}
    out = {}
    for name, value in (raw or {}).items():
        try:
            out[name] = json.loads(value)
        except ValueError:
            continue
    return out


async def _save_health(updates: dict[str, dict]) -> None:
    if not updates:
        return
    client = await get_client()
    if client is None:
        _memory_health.update(updates)
        return
    try:
        await client.hset(HEALTH_KEY, mapping={k: json.dumps(v) for k, v in updates.items()})
    except Exception:  # noqa: BLE001
        pass


def is_paused(record: dict | None, now: float | None = None) -> bool:
    return bool(record) and (now or time.time()) < float(record.get("paused_until") or 0)


def _next_record(record: dict | None, state: str, now: float) -> dict:
    record = dict(record or {})
    recent = (list(record.get("recent") or []) + [state])[-HEALTH_WINDOW:]
    record["recent"] = recent
    record["last_run"] = now
    if len(recent) >= UNKNOWN_PAUSE_AFTER and all(s == "unknown" for s in recent[-UNKNOWN_PAUSE_AFTER:]):
        record["paused_until"] = now + UNKNOWN_PAUSE_SECONDS
        record["pause_reason"] = f"no usable answer in the last {UNKNOWN_PAUSE_AFTER} checks"
        record["recent"] = []   # give it a clean slate after the pause
    return record


# ---- running ----

_site_locks: dict[str, asyncio.Lock] = {}
_site_last_call: dict[str, float] = {}


async def _respect_site_interval(name: str) -> None:
    lock = _site_locks.setdefault(name, asyncio.Lock())
    async with lock:
        wait = _site_last_call.get(name, 0) + MIN_INTERVAL_PER_SITE_SECONDS - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _site_last_call[name] = time.monotonic()


def classify(out: list[dict]) -> tuple[str, dict]:
    """Holehe's out-list for one module -> (state, its row)."""
    row = out[0] if out else {}
    if not row or row.get("rateLimit"):
        return "unknown", row
    return ("used" if row.get("exists") else "not_used"), row


async def _run_modules(email: str, modules: list[HoleheModule]) -> list[tuple[HoleheModule, str, dict]]:
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def one(client: httpx.AsyncClient, module: HoleheModule):
        async with semaphore:
            await _respect_site_interval(module.name)
            out: list[dict] = []
            try:
                await asyncio.wait_for(module.func(email, client, out), timeout=MODULE_TIMEOUT_SECONDS + 3)
            except Exception:  # noqa: BLE001 - a broken module is just "unknown"
                out = []
            state, row = classify(out)
            return module, state, row

    async with httpx.AsyncClient(timeout=MODULE_TIMEOUT_SECONDS, follow_redirects=False) as client:
        return await asyncio.gather(*(one(client, m) for m in modules))


async def _record(outcomes: list[tuple[HoleheModule, str, dict]], health: dict) -> None:
    now = time.time()
    await _save_health({m.name: _next_record(health.get(m.name), state, now) for m, state, _ in outcomes})


async def run_holehe(email: str) -> dict:
    email = positional_arg(email)
    health = await load_health()
    allowed = [m for m in available_modules() if policy_allows(m)]
    active = [m for m in allowed if not is_paused(health.get(m.name))]
    if not active:
        raise ToolError("no Holehe module is currently available")

    outcomes = await _run_modules(email, active)
    await _record(outcomes, health)

    used = sorted((row.get("domain") or m.name for m, s, row in outcomes if s == "used"))
    unknown = sorted((row.get("domain") or m.name for m, s, row in outcomes if s == "unknown"))
    not_used = sum(1 for _m, s, _r in outcomes if s == "not_used")
    if not used and not not_used:
        raise ToolError(f"none of {len(active)} sites gave a usable answer (rate limits or errors)")

    results = [
        {
            "platform": domain,
            "url": f"https://{domain}",
            "status": "registered",
            "signal": "registration",
            "info": SIGNAL_INFO,
        }
        for domain in used
    ]
    paused = len(allowed) - len(active)
    summary = (
        f"Sign-up checks on {len(active)} sites: {len(used)} say registered, "
        f"{not_used} say not registered, {len(unknown)} could not be checked"
        + (f" ({', '.join(unknown[:12])}{' ...' if len(unknown) > 12 else ''})" if unknown else "")
        + (f"; {paused} site check(s) paused as unreliable" if paused else "")
        + ". Password-recovery and login checks are never run."
    )
    results.append({
        "platform": "Registration checks (Holehe)",
        "url": "https://github.com/megadose/holehe",
        "status": "info",
        "source": "run_summary",   # changes every run: not watched for change
        "info": summary,
    })
    return {"tool": "holehe", "results": results, "used": used, "unknown": unknown,
            "checked": len(active)}


async def run_canary() -> dict:
    """Daily: ask every module about a random address nobody has registered.

    A module that says "registered" for it is producing false positives and
    is paused for a week. Needs no real person's data.
    """
    address = f"nx{secrets.token_hex(8)}@gmail.com"
    health = await load_health()
    modules = [m for m in available_modules() if policy_allows(m)]
    outcomes = await _run_modules(address, modules)
    now = time.time()
    updates = {}
    broken = []
    for module, state, _row in outcomes:
        record = _next_record(health.get(module.name), state, now)
        if state == "used":
            record["paused_until"] = now + FALSE_POSITIVE_PAUSE_SECONDS
            record["pause_reason"] = "reported a random, never-used address as registered"
            broken.append(module.name)
        updates[module.name] = record
    await _save_health(updates)
    return {"checked": len(modules), "false_positives": sorted(broken),
            "unknown": sum(1 for _m, s, _r in outcomes if s == "unknown")}


async def health_summary() -> dict:
    health = await load_health()
    modules = available_modules()
    allowed = [m for m in modules if policy_allows(m)]
    paused = {m.name: health[m.name].get("pause_reason", "") for m in allowed if is_paused(health.get(m.name))}
    return {"total": len(modules), "allowed": len(allowed), "paused": paused,
            "excluded_by_policy": len(modules) - len(allowed)}
