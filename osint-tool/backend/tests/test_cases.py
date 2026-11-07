import importlib

import pytest


@pytest.fixture()
def store_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CASES_DB_PATH", str(tmp_path / "cases.db"))
    import store
    importlib.reload(store)
    store.init_db()
    return store


def test_create_list_and_get_case(store_mod):
    case = store_mod.create_case("  Acme  investigation ")
    assert case["name"] == "Acme investigation"
    cases = store_mod.list_cases()
    assert len(cases) == 1 and cases[0]["findings"] == 0
    detail = store_mod.get_case(case["id"])
    assert detail["case"]["name"] == "Acme investigation"
    assert detail["findings"] == []


def test_add_finding_updates_count_and_provenance(store_mod):
    case = store_mod.create_case("c1")
    store_mod.add_finding(case["id"], "domain", "example.com",
                          {"status": "success", "count": 3})
    detail = store_mod.get_case(case["id"])
    assert len(detail["findings"]) == 1
    f = detail["findings"][0]
    assert f["category"] == "domain" and f["query"] == "example.com"
    assert f["result"]["count"] == 3
    assert f["created_at"]  # timestamp recorded
    assert store_mod.list_cases()[0]["findings"] == 1


def test_delete_finding_and_case(store_mod):
    case = store_mod.create_case("c1")
    f = store_mod.add_finding(case["id"], "name", "x", {"a": 1})
    store_mod.delete_finding(case["id"], f["id"])
    assert store_mod.get_case(case["id"])["findings"] == []
    store_mod.delete_case(case["id"])
    assert store_mod.list_cases() == []


def test_errors(store_mod):
    with pytest.raises(store_mod.CaseError):
        store_mod.create_case("   ")
    with pytest.raises(store_mod.CaseError):
        store_mod.get_case("nope")
    with pytest.raises(store_mod.CaseError):
        store_mod.add_finding("nope", "name", "x", {})
    with pytest.raises(store_mod.CaseError):
        store_mod.delete_case("nope")
