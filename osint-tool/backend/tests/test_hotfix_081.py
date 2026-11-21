"""v0.8.1 hotfix (ROADMAP 8b.1-8b.6): host guard, audit flooding, robust
full deletion, reserved user names, retention parsing."""
import importlib
import sqlite3

import pytest
from httpx import ASGITransport, AsyncClient

from security import allowed_hosts, configured_users, host_allowed, limiter, weak_key_warnings


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("CASES_DB_PATH", str(tmp_path / "cases.db"))
    for name in ("OSINT_API_KEY", "OSINT_USERS", "ALLOW_OPEN_ACCESS", "AUDIT_LOG_QUERIES"):
        monkeypatch.delenv(name, raising=False)
    import store
    importlib.reload(store)
    store.init_db()
    from tools import passive_dns
    monkeypatch.setattr(passive_dns, "DB_PATH", str(tmp_path / "pdns.db"))
    import main
    monkeypatch.setattr(main, "_refused", {})
    limiter.reset()
    yield main, store
    limiter.reset()


def client(main, base="http://localhost:8000", host="127.0.0.1"):
    return AsyncClient(transport=ASGITransport(app=main.app, client=(host, 5000)), base_url=base)


# ---------------- 8b.1 DNS rebinding ----------------

def test_allowed_hosts_rules(monkeypatch):
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("OSINT_API_KEY", raising=False)
    monkeypatch.delenv("OSINT_USERS", raising=False)
    assert host_allowed("localhost:8000") and host_allowed("127.0.0.1:8000") and host_allowed("[::1]:8000")
    assert not host_allowed("evil.example:8000") and not host_allowed(None)
    monkeypatch.setenv("OSINT_API_KEY", "admin-key-1234567890")
    assert allowed_hosts() is None and host_allowed("osint.example.org")     # keys: no rebinding risk
    monkeypatch.setenv("ALLOWED_HOSTS", "osint.example.org")
    assert host_allowed("osint.example.org:443") and not host_allowed("localhost")
    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    assert host_allowed("anything")


@pytest.mark.asyncio
async def test_rebound_host_cannot_wipe_or_read_audit(app, monkeypatch):
    main, store = app
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    case = store.create_case("keep me")
    # the browser of a rebinding page sends its own name as Host, from 127.0.0.1
    async with client(main, base="http://rebind.attacker.example:8000") as c:
        wipe = await c.request("DELETE", "/api/data", json={"confirm": "DELETE ALL", "include_audit": True})
        audit = await c.get("/api/audit")
    assert wipe.status_code == 400 and audit.status_code == 400
    assert "ALLOWED_HOSTS" in wipe.json()["message"]
    assert store.get_case(case["id"])["case"]["name"] == "keep me"
    async with client(main) as c:
        assert (await c.get("/api/whoami")).status_code == 200


@pytest.mark.asyncio
async def test_keyless_wipe_only_from_the_console_origin(app):
    main, store = app
    store.create_case("keep me")
    async with client(main, base="http://localhost") as c:
        other = await c.request("DELETE", "/api/data", json={"confirm": "DELETE ALL"},
                                headers={"Origin": "http://evil.example"})
        assert other.status_code == 403 and store.list_cases()
        console = await c.request("DELETE", "/api/data", json={"confirm": "DELETE ALL"},
                                  headers={"Origin": "http://localhost:8080"})
        assert console.status_code == 200 and store.list_cases() == []


# ---------------- 8b.2 audit flooding ----------------

@pytest.mark.asyncio
async def test_unknown_paths_are_not_audited(app):
    main, store = app
    async with client(main) as c:
        for i in range(5):
            await c.post(f"/api/made-up-{i}", json={"query": "x"})
        await c.post("/api/cases", json={"name": "real"})
    assert [e["path"] for e in store.list_audit()] == ["/api/cases"]


@pytest.mark.asyncio
async def test_rejected_requests_are_capped_per_ip(app, monkeypatch):
    main, store = app
    monkeypatch.setenv("OSINT_API_KEY", "admin-key-1234567890")
    monkeypatch.setattr(main, "REFUSED_PER_MINUTE", 3)
    async with client(main) as c:
        for _ in range(10):
            assert (await c.post("/api/cases", json={"name": "x"}, headers={"X-API-Key": "wrong"})).status_code == 401
    refused = [e for e in store.list_audit() if e["user"] == "refused"]
    assert len(refused) == 3
    # the next window writes one summary of what was dropped
    gate, ended = main._refused_gate("127.0.0.1", 10**9)
    assert gate and ended == 7


# ---------------- 8b.3 full deletion is reported honestly ----------------

@pytest.mark.asyncio
async def test_wipe_reports_a_busy_database_and_still_clears_the_cache(app, monkeypatch):
    main, store = app
    from cache import get_cached_json, set_cached_json
    from services import data_wipe

    store.create_case("Ali")
    await set_cached_json("osint:name:ali", {"results": []}, 60)
    reader = sqlite3.connect(store.DB_PATH)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM cases").fetchall()            # an open read holds the WAL
    try:
        out = await data_wipe.wipe_everything()
    finally:
        reader.close()
    assert out["deleted"]["cases"] == 1
    assert out["warnings"] and "busy" in out["warning"]
    assert await get_cached_json("osint:name:ali") is None


@pytest.mark.asyncio
async def test_wipe_survives_a_database_error(app, monkeypatch):
    main, store = app
    from cache import get_cached_json, set_cached_json
    from services import data_wipe

    def broken(include_audit=False):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(data_wipe.store, "wipe_all", broken)
    await set_cached_json("osint:name:ali", {"results": []}, 60)
    out = await data_wipe.wipe_everything()
    assert "not cleared" in out["warning"]
    assert await get_cached_json("osint:name:ali") is None      # the cache step still ran


# ---------------- 8b.6 everything means everything ----------------

@pytest.mark.asyncio
async def test_wipe_clears_passive_dns_and_blocks_late_answers(app):
    main, store = app
    from services import data_wipe, investigate
    from tools import passive_dns
    from cache import clear_memory_cache, get_cached_json

    clear_memory_cache()
    pdns = passive_dns.DB_PATH                                   # the fixture's temporary store
    passive_dns.record_self("target.uz", [("A", ["1.2.3.4"])], path=pdns)
    assert passive_dns.history("target.uz", path=pdns)

    async def slow_search(q):
        await data_wipe.wipe_everything()                        # deletion happens mid-search
        return {"status": "success", "results": [{"url": "https://target.uz"}]}

    await investigate._cached("osint:late:1", slow_search, "q")
    assert await get_cached_json("osint:late:1") is None        # the late answer is not cached
    assert passive_dns.history("target.uz", path=pdns) == []


@pytest.mark.asyncio
async def test_worker_drops_a_result_finished_after_a_wipe(app, monkeypatch):
    import worker
    from services import data_wipe

    async def search(category, query):
        await data_wipe.wipe_everything()
        return {"status": "success", "results": []}

    monkeypatch.setattr(worker, "investigate", search)
    out = await worker.run_investigation({}, "name", "Ali")
    assert out["status"] == "error" and "deleted" in out["message"]


# ---------------- 8b.4 / 8b.5 ----------------

def test_reserved_user_names_are_ignored(monkeypatch):
    monkeypatch.delenv("OSINT_API_KEY", raising=False)
    monkeypatch.setenv("OSINT_USERS", "admin:sneaky-admin-key-123,Local:x-key-1234567890123,"
                                      "refused:y-key-12345678901234,alice:alice-key-123456789")
    assert set(configured_users().values()) == {"alice"}
    warnings = weak_key_warnings()
    assert sum("reserved" in w for w in warnings) == 3


def test_bad_retention_value_does_not_crash(monkeypatch):
    import store
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "ninety")
    assert store._retention_days() == 90
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "-5")
    assert store._retention_days() == 0
