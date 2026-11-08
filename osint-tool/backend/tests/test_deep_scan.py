import pytest

from services import deep_scan
from services.investigate import InvestigationValidationError


def test_detect_type():
    assert deep_scan.detect_type("you@example.com") == "email"
    assert deep_scan.detect_type("+14155552671") == "phone"
    assert deep_scan.detect_type("14155552671") == "phone"
    assert deep_scan.detect_type("example.com") == "domain"
    assert deep_scan.detect_type("8.8.8.8") == "domain"
    assert deep_scan.detect_type("johndoe") == "username"
    assert deep_scan.detect_type("John Doe") == "name"


@pytest.mark.asyncio
async def test_rejects_empty_seed():
    with pytest.raises(InvestigationValidationError):
        await deep_scan.run_deep_scan("")


@pytest.mark.asyncio
async def test_rejects_unknown_type():
    with pytest.raises(InvestigationValidationError):
        await deep_scan.run_deep_scan("x", "image")


def _fake(category, results, pivots=None):
    async def handler(value):
        return {
            "status": "success",
            "category": category,
            "query": value,
            "results": results,
            "count": len(results),
            "pivots": pivots or [],
        }
    return handler


@pytest.mark.asyncio
async def test_follows_pivots_and_builds_edges(monkeypatch):
    # username -> yields a domain pivot -> domain investigator runs
    monkeypatch.setitem(
        deep_scan._HANDLERS,
        "username",
        _fake("username", [{"platform": "GitHub"}], [{"type": "domain", "value": "acme.com"}]),
    )
    monkeypatch.setitem(
        deep_scan._HANDLERS,
        "domain",
        _fake("domain", [{"platform": "DNS"}], []),
    )
    data = await deep_scan.run_deep_scan("johndoe", "username")
    assert data["status"] == "success"
    assert data["seed_type"] == "username"
    assert data["node_count"] == 2
    types = {n["type"] for n in data["nodes"]}
    assert types == {"username", "domain"}
    assert {"from": "username:johndoe", "to": "host:acme.com"} in data["edges"]


@pytest.mark.asyncio
async def test_respects_depth_limit(monkeypatch):
    # each domain points to the next domain; depth cap must stop the chain
    def chain(value):
        async def handler(v):
            nxt = v + ".x"
            return {
                "status": "success",
                "category": "domain",
                "query": v,
                "results": [],
                "count": 0,
                "pivots": [{"type": "domain", "value": nxt}],
            }
        return handler
    monkeypatch.setitem(deep_scan._HANDLERS, "domain", chain("seed"))
    monkeypatch.setattr(deep_scan, "MAX_DEPTH", 2)
    data = await deep_scan.run_deep_scan("seed.com", "domain")
    assert max(n["depth"] for n in data["nodes"]) <= deep_scan.MAX_DEPTH


@pytest.mark.asyncio
async def test_dedupes_shared_pivot(monkeypatch):
    # two usernames both pivot to the same domain -> one domain node, two edges
    monkeypatch.setitem(
        deep_scan._HANDLERS,
        "name",
        _fake("name", [], [
            {"type": "username", "value": "a"},
            {"type": "username", "value": "b"},
        ]),
    )
    monkeypatch.setitem(
        deep_scan._HANDLERS,
        "username",
        _fake("username", [], [{"type": "domain", "value": "shared.com"}]),
    )
    monkeypatch.setitem(deep_scan._HANDLERS, "domain", _fake("domain", [], []))
    data = await deep_scan.run_deep_scan("Jane Roe", "name")
    host_nodes = [n for n in data["nodes"] if n["type"] == "domain"]
    assert len(host_nodes) == 1
    edges_to_host = [e for e in data["edges"] if e["to"] == "host:shared.com"]
    assert len(edges_to_host) == 2


def _assert_edges_reference_real_nodes(data):
    keys = {n["key"] for n in data["nodes"]}
    for e in data["edges"]:
        assert e["from"] in keys, f"dangling edge from {e['from']}"
        assert e["to"] in keys, f"dangling edge to {e['to']}"


@pytest.mark.asyncio
async def test_skips_rejected_pivot_quietly(monkeypatch):
    async def bad(value):
        raise InvestigationValidationError("nope")
    monkeypatch.setitem(
        deep_scan._HANDLERS,
        "username",
        _fake("username", [], [{"type": "domain", "value": "bad"}]),
    )
    monkeypatch.setitem(deep_scan._HANDLERS, "domain", bad)
    data = await deep_scan.run_deep_scan("u", "username")
    # the rejected domain produces no node and no warning
    assert all(n["type"] != "domain" for n in data["nodes"])
    assert not data.get("warnings")
    # and crucially no edge pointing at the node that was never created
    _assert_edges_reference_real_nodes(data)
    assert data["edges"] == []


@pytest.mark.asyncio
async def test_truncation_never_leaves_dangling_edges(monkeypatch):
    # a domain that fans out to many fresh domains, so MAX_NODES is hit while
    # cross-link / pending pivots still exist — every emitted edge must still
    # reference a node that actually made it into the result.
    def handler_factory():
        async def handler(v):
            pivots = [{"type": "domain", "value": f"{v}-{i}.com"} for i in range(6)]
            # also point back at the seed to force a cross-link edge
            pivots.append({"type": "domain", "value": "seed.com"})
            return {
                "status": "success",
                "category": "domain",
                "query": v,
                "results": [],
                "count": 0,
                "pivots": pivots,
            }
        return handler
    monkeypatch.setitem(deep_scan._HANDLERS, "domain", handler_factory())
    monkeypatch.setattr(deep_scan, "MAX_NODES", 8)
    monkeypatch.setattr(deep_scan, "MAX_DEPTH", 3)
    data = await deep_scan.run_deep_scan("seed.com", "domain")
    assert data["truncated"] is True
    assert data["node_count"] <= 8
    _assert_edges_reference_real_nodes(data)
