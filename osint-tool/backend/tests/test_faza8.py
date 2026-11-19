"""Faza 8: provenance times, full deletion, audit log, access control."""
import importlib

import pytest
from httpx import ASGITransport, AsyncClient

from security import limiter, user_for
from services import provenance


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("CASES_DB_PATH", str(tmp_path / "cases.db"))
    for name in ("OSINT_API_KEY", "OSINT_USERS", "ALLOW_OPEN_ACCESS", "AUDIT_LOG_QUERIES"):
        monkeypatch.delenv(name, raising=False)
    import store
    importlib.reload(store)
    store.init_db()
    limiter.reset()
    import main
    yield main, store
    limiter.reset()


def client(main, host="127.0.0.1"):
    return AsyncClient(transport=ASGITransport(app=main.app, client=(host, 5000)), base_url="http://test")


# ---------------- 8.1 provenance ----------------

def test_stamp_marks_every_result_once():
    result = {"results": [{"url": "https://a.uz"}, {"url": "https://b.uz", "retrieved_at": "old"}],
              "sections": [{"results": [{"url": "https://c.uz"}]}]}
    provenance.stamp(result, "2026-11-19T10:00:00+00:00")
    assert result["retrieved_at"] == "2026-11-19T10:00:00+00:00"
    assert result["results"][0]["retrieved_at"] == "2026-11-19T10:00:00+00:00"
    assert result["results"][1]["retrieved_at"] == "old"            # kept
    assert result["sections"][0]["results"][0]["retrieved_at"] == "2026-11-19T10:00:00+00:00"
    provenance.stamp(result, "2030-01-01T00:00:00+00:00")
    assert result["retrieved_at"] == "2026-11-19T10:00:00+00:00"    # a second stamp changes nothing
    assert provenance.stamp("text") == "text"


@pytest.mark.asyncio
async def test_cached_answer_keeps_original_time(monkeypatch):
    from cache import clear_memory_cache
    from services import investigate

    clear_memory_cache()
    monkeypatch.setattr(investigate, "CACHE_TTL", 60, raising=False)

    async def producer(q):
        return {"status": "success", "results": [{"url": "https://x.uz", "platform": "X"}]}

    first = await investigate._cached("osint:test:prov", producer, "q")
    monkeypatch.setattr(provenance, "now_iso", lambda: "2099-01-01T00:00:00+00:00")
    second = await investigate._cached("osint:test:prov", producer, "q")
    assert second.get("cached") and second["retrieved_at"] == first["retrieved_at"]
    assert second["results"][0]["retrieved_at"] == first["retrieved_at"]


def test_saved_finding_carries_retrieval_time(app):
    _, store = app
    case = store.create_case("c")
    store.add_finding(case["id"], "name", "ali", {"results": [{"url": "https://a.uz"}]})
    finding = store.get_case(case["id"])["findings"][0]
    assert finding["result"]["results"][0]["retrieved_at"] == finding["created_at"]


def test_agent_field_sources_keep_retrieval_time():
    from services.agent import profile_fields
    members = [{"type": "username", "query": "ali", "results": [
        {"platform": "GitHub", "url": "https://github.com/ali", "status": "found",
         "info": "Name: Ali Valiyev", "retrieved_at": "2026-11-19T09:00:00+00:00"}]}]
    fields = profile_fields(members)
    sources = [s for v in fields["name"] for s in v["sources"]]
    assert any(s.get("retrieved_at") == "2026-11-19T09:00:00+00:00" for s in sources)


def test_person_card_prints_retrieval_time():
    from services.person_card import _sources_text
    text = _sources_text([{"platform": "GitHub", "url": "https://github.com/a",
                           "retrieved_at": "2026-11-19T09:05:00+00:00"}])
    assert "(2026-11-19 09:05 UTC)" in text


# ---------------- 8.4 access ----------------

def test_user_for_rules(monkeypatch):
    for name in ("OSINT_API_KEY", "OSINT_USERS", "ALLOW_OPEN_ACCESS"):
        monkeypatch.delenv(name, raising=False)
    assert user_for(None, "127.0.0.1") == "local"
    assert user_for(None, "172.18.0.1") == "local"            # docker bridge
    assert user_for(None, "::ffff:192.168.1.5") == "local"
    assert user_for(None, "8.8.8.8") is None                  # exposed without a key
    monkeypatch.setenv("ALLOW_OPEN_ACCESS", "1")
    assert user_for(None, "8.8.8.8") == "local"
    monkeypatch.setenv("OSINT_USERS", "alice:alice-key-123456789,bad name:x,bob:bob-key-1234567890")
    monkeypatch.setenv("OSINT_API_KEY", "admin-key-1234567890")
    assert user_for("alice-key-123456789", "8.8.8.8") == "alice"
    assert user_for("admin-key-1234567890", "127.0.0.1") == "admin"
    assert user_for(None, "127.0.0.1") is None                # keys set: also local needs one
    assert user_for("x", "127.0.0.1") is None


@pytest.mark.asyncio
async def test_public_client_without_keys_is_refused(app):
    main, _ = app
    async with client(main, "8.8.8.8") as c:
        r = await c.get("/api/cases")
        assert r.status_code == 403 and "OSINT_API_KEY" in r.json()["detail"]
        assert (await c.get("/health")).status_code == 200
    async with client(main) as c:
        assert (await c.get("/api/cases")).status_code == 200


@pytest.mark.asyncio
async def test_named_users_and_admin_only_routes(app, monkeypatch):
    main, _ = app
    monkeypatch.setenv("OSINT_USERS", "alice:alice-key-123456789")
    monkeypatch.setenv("OSINT_API_KEY", "admin-key-1234567890")
    async with client(main) as c:
        assert (await c.get("/api/whoami")).status_code == 401
        me = await c.get("/api/whoami", headers={"X-API-Key": "alice-key-123456789"})
        assert me.json() == {"user": "alice", "admin": False, "keys_configured": True,
                             "audit_retention_days": 90}
        assert (await c.get("/api/audit", headers={"X-API-Key": "alice-key-123456789"})).status_code == 403
        assert (await c.request("DELETE", "/api/data", json={"confirm": "DELETE ALL"},
                                headers={"X-API-Key": "alice-key-123456789"})).status_code == 403
        assert (await c.get("/api/audit", headers={"X-API-Key": "admin-key-1234567890"})).status_code == 200


def test_weak_keys_are_reported(monkeypatch):
    from security import weak_key_warnings
    monkeypatch.setenv("OSINT_API_KEY", "short")
    monkeypatch.delenv("OSINT_USERS", raising=False)
    assert weak_key_warnings() == ["API key of 'admin' is shorter than 16 characters"]


# ---------------- 8.3 audit ----------------

@pytest.mark.asyncio
async def test_audit_records_who_what_when(app, monkeypatch):
    main, store = app
    monkeypatch.setenv("OSINT_USERS", "alice:alice-key-123456789")
    monkeypatch.setenv("OSINT_API_KEY", "admin-key-1234567890")
    monkeypatch.setenv("RATE_LIMIT_LIGHT", "100/minute")
    alice = {"X-API-Key": "alice-key-123456789"}
    async with client(main) as c:
        await c.post("/api/name", json={"query": "!!!@@@"}, headers=alice)       # 400, still audited
        await c.post("/api/cases", json={"name": "Case A"}, headers=alice)
        await c.get("/api/cases", headers=alice)                               # plain list: not audited
        await c.post("/api/name", json={"query": "x"}, headers={"X-API-Key": "wrong"})
        entries = (await c.get("/api/audit", headers={"X-API-Key": "admin-key-1234567890"})).json()["entries"]
    by_path = [(e["user"], e["method"], e["path"], e["query"], e["status"]) for e in reversed(entries)]
    assert by_path[:3] == [("alice", "POST", "/api/name", "!!!@@@", 400),
                           ("alice", "POST", "/api/cases", "Case A", 200),
                           ("refused", "POST", "/api/name", "x", 401)]
    assert all(e["at"].endswith("+00:00") and e["client"] == "127.0.0.1" for e in entries)
    assert store.list_audit(user="alice", search="Case")[0]["query"] == "Case A"


@pytest.mark.asyncio
async def test_audit_can_keep_only_a_hash(app, monkeypatch):
    main, store = app
    monkeypatch.setenv("AUDIT_LOG_QUERIES", "0")
    async with client(main) as c:
        await c.post("/api/cases", json={"name": "Secret Person"})
    entry = store.list_audit()[0]
    assert entry["query"].startswith("sha256:") and "Secret" not in entry["query"]


def test_audit_retention_drops_old_entries(app, monkeypatch):
    _, store = app
    store.add_audit({"at": "2000-01-01T00:00:00+00:00", "user": "a", "method": "POST", "path": "/api/x"})
    store.add_audit({"user": "b", "method": "POST", "path": "/api/y"})
    assert [e["user"] for e in store.list_audit()] == ["b"]


# ---------------- 8.2 deletion ----------------

@pytest.mark.asyncio
async def test_delete_agent_run_and_late_steps(app):
    main, store = app
    run = store.create_agent_run("ali valiyev")
    store.add_agent_step(run["id"], "info", "x")
    store.update_agent_run(run["id"], status="complete", result={"candidates": [{"id": "c1"}]})
    store.set_agent_decision(run["id"], "c1", "confirmed", "")
    async with client(main) as c:
        assert (await c.delete(f"/api/agent/{run['id']}")).status_code == 200
        assert (await c.delete(f"/api/agent/{run['id']}")).status_code == 404
    store.add_agent_step(run["id"], "info", "late step from the worker")
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_steps").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM agent_decisions").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_wipe_everything(app, tmp_path):
    main, store = app
    from cache import get_cached_json, set_cached_json
    case = store.create_case("Ali case")
    store.add_finding(case["id"], "name", "Ali Valiyev", {"results": [{"url": "https://a.uz"}]})
    store.create_agent_run("Ali Valiyev")
    store.create_watch("w", "username", "alivaliyev", 60)
    await set_cached_json("osint:name:ali valiyev", {"results": []}, 60)
    async with client(main) as c:
        bad = await c.request("DELETE", "/api/data", json={"confirm": "yes"})
        assert bad.status_code == 400 and "DELETE ALL" in bad.json()["message"]
        ok = await c.request("DELETE", "/api/data", json={"confirm": "DELETE ALL"})
        body = ok.json()
    assert ok.status_code == 200 and body["deleted"]["cases"] == 1 and body["deleted"]["findings"] == 1
    assert "audit_log" not in body["deleted"]
    assert store.list_cases() == [] and store.list_agent_runs() == [] and store.list_watches() == []
    assert await get_cached_json("osint:name:ali valiyev") is None
    assert store.list_audit()[0]["path"] == "/api/data"                 # the wipe itself is recorded
    raw = (tmp_path / "cases.db").read_bytes()
    assert b"Ali Valiyev" not in raw and b"alivaliyev" not in raw       # not left in free pages


@pytest.mark.asyncio
async def test_wipe_can_include_the_audit_log(app):
    main, store = app
    async with client(main) as c:
        await c.post("/api/cases", json={"name": "Ali"})
        r = await c.request("DELETE", "/api/data", json={"confirm": "DELETE ALL", "include_audit": True})
    assert r.json()["deleted"]["audit_log"] >= 1
    assert [e["path"] for e in store.list_audit()] == ["/api/data"]    # only the wipe request remains
