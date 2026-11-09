import importlib

import pytest

from services import monitor


@pytest.fixture()
def store_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CASES_DB_PATH", str(tmp_path / "cases.db"))
    import store
    importlib.reload(store)
    store.init_db()
    # monitor holds its own reference to the store module; point it at the fresh one
    monkeypatch.setattr(monitor, "store", store)
    return store


# ---- signature / diff ----

def test_signature_items_is_canonical():
    result = {"results": [
        {"platform": "GitHub", "url": "https://github.com/x", "status": "found"},
        {"platform": "GitLab", "url": "https://gitlab.com/x", "status": "found"},
    ]}
    sig = monitor.signature_items(result)
    assert sig == sorted(sig)  # order-stable
    assert "GitHub|https://github.com/x|found" in sig


def test_diff_summary_detects_add_and_remove():
    old = ["A|u|found", "B|v|found"]
    new = ["A|u|found", "C|w|found"]
    summary = monitor._diff_summary(old, new)
    assert "+1 new" in summary and "-1 removed" in summary
    assert monitor._diff_summary(old, old) is None


# ---- storage ----

def test_watch_crud_and_due(store_mod):
    w = store_mod.create_watch("Acme watch", "domain", "example.com", 60)
    assert w["active"] is True and w["events"] == []
    assert store_mod.list_watches()[0]["name"] == "Acme watch"
    # never checked -> due
    assert any(d["id"] == w["id"] for d in store_mod.due_watches())
    store_mod.set_watch_active(w["id"], False)
    assert store_mod.due_watches() == []
    store_mod.delete_watch(w["id"])
    with pytest.raises(store_mod.CaseError):
        store_mod.get_watch(w["id"])


def test_invalid_interval_rejected(store_mod):
    with pytest.raises(store_mod.CaseError):
        store_mod.create_watch("x", "domain", "example.com", 1)  # below MIN_INTERVAL


def test_record_check_logs_event_only_on_change(store_mod):
    w = store_mod.create_watch("w", "domain", "example.com", 60)
    store_mod.record_watch_check(w["id"], "h1", "no change", None)
    assert store_mod.get_watch(w["id"])["events"] == []
    store_mod.record_watch_check(w["id"], "h2", "changed", "+1 new")
    events = store_mod.get_watch(w["id"])["events"]
    assert len(events) == 1 and events[0]["summary"] == "+1 new"


# ---- check_watch baseline then change ----

@pytest.mark.asyncio
async def test_check_watch_baseline_then_change(store_mod, monkeypatch):
    w = store_mod.create_watch("w", "username", "someone", 60)

    async def fake_one(category, query):
        return {"status": "success", "results": [
            {"platform": "GitHub", "url": "https://github.com/someone", "status": "found"},
        ]}
    monkeypatch.setattr(monitor, "investigate", fake_one)

    first = await monitor.check_watch(store_mod.get_watch(w["id"]))
    assert first["status"] == "baseline"
    assert store_mod.get_watch(w["id"])["events"] == []  # no event on baseline

    async def fake_two(category, query):
        return {"status": "success", "results": [
            {"platform": "GitHub", "url": "https://github.com/someone", "status": "found"},
            {"platform": "GitLab", "url": "https://gitlab.com/someone", "status": "found"},
        ]}
    monkeypatch.setattr(monitor, "investigate", fake_two)

    second = await monitor.check_watch(store_mod.get_watch(w["id"]))
    assert second["status"] == "changed"
    assert "+1 new" in second["summary"]
    events = store_mod.get_watch(w["id"])["events"]
    assert len(events) == 1

    # third run, unchanged -> no new event
    third = await monitor.check_watch(store_mod.get_watch(w["id"]))
    assert third["status"] == "no change"
    assert len(store_mod.get_watch(w["id"])["events"]) == 1


@pytest.mark.asyncio
async def test_check_watch_handles_investigator_error(store_mod, monkeypatch):
    w = store_mod.create_watch("w", "domain", "example.com", 60)

    async def boom(category, query):
        raise RuntimeError("upstream down")
    monkeypatch.setattr(monitor, "investigate", boom)

    outcome = await monitor.check_watch(store_mod.get_watch(w["id"]))
    assert outcome["status"] == "error"
    refreshed = store_mod.get_watch(w["id"])
    assert refreshed["last_status"].startswith("error")
    assert refreshed["events"] == []  # errors are not change events
