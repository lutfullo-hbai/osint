"""Regressions for the Faza 1b review findings (R1-R11, 1.9, 1.10, 1.11)."""
import importlib
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import cache
import main
from services import correlate as corr
from services import investigate as inv
from services import monitor
from tools import base, entity_intel, net_guard, public_profiles, sherlock_runner, truecaller
from tools.hub_domains import is_hub_domain


# ---- R1: Wikidata namesakes are not knowledge-base evidence ----

def _detail(title, handle, human=True):
    entry = {"platform": "Wikidata", "title": title}
    return entry, [{"type": "username", "value": handle}], human


def test_two_humans_with_the_same_name_are_only_candidates():
    pivots = entity_intel._grade_pivots("Michael Jordan", [
        _detail("Michael Jordan", "jumpman23"),
        _detail("Michael Jordan", "mijordan"),
    ])
    assert {p["via"] for p in pivots} == {"name_match"}


def test_unique_matching_human_is_knowledge_base():
    pivots = entity_intel._grade_pivots("linus torvalds", [
        _detail("Linus Torvalds", "torvalds"),
        _detail("Linus Torvalds (film)", "notaperson", human=False),
    ])
    assert pivots == [{"type": "username", "value": "torvalds", "via": "knowledge_base"}]


def test_label_mismatch_and_apostrophes():
    pivots = entity_intel._grade_pivots("Jane Roe", [_detail("Jane Roe-Smith", "jrs")])
    assert pivots[0]["via"] == "name_match"
    pivots = entity_intel._grade_pivots("Sho'xrux Aliyev", [_detail("Shoʻxrux Aliyev", "shox")])
    assert pivots[0]["via"] == "knowledge_base"


# ---- R2: shared platforms never become domain pivots ----

def test_hub_domains():
    assert is_hub_domain("linkedin.com") and is_hub_domain("www.linkedin.com")
    assert is_hub_domain("jane.github.io") and is_hub_domain("gmail.com")
    assert not is_hub_domain("janedoe.dev") and not is_hub_domain("notgithub.io")


def test_profile_website_on_hub_is_not_a_pivot():
    entries = [
        {"platform": "GitHub", "website": "https://www.linkedin.com/in/jane"},
        {"platform": "Dev.to", "website": "https://janedoe.dev"},
    ]
    pivots = public_profiles.extract_pivots(entries)
    assert [p["value"] for p in pivots if p["type"] == "domain"] == ["janedoe.dev"]


# ---- R3: profile URLs need an exact host and a real user path ----

@pytest.mark.parametrize("url,handle", [
    ("https://netflix.com/title/1", None),
    ("https://budget.me/janedoe", None),
    ("https://github.com/topics/osint", None),
    ("https://evilgithub.com/x", None),
    ("https://x.com/i/status/1", None),
    ("https://github.com/torvalds", "torvalds"),
    ("https://www.reddit.com/u/spez/", "spez"),
    ("https://twitter.com/jack/status/1", "jack"),
    ("https://news.ycombinator.com/user?id=pg", "pg"),
    ("https://t.me/durov", "durov"),
])
def test_handle_from_url(url, handle):
    assert corr.handle_from_url(url) == handle


# ---- R4: an email local-part is counted once; provenance survives cases ----

def test_localpart_counts_once():
    nodes = [
        {"key": "email:janedoe@x.org", "type": "email", "query": "janedoe@x.org",
         "results": [], "pivots": [{"type": "username", "value": "janedoe",
                                    "via": "email_localpart"}]},
        {"key": "username:janedoe", "type": "username", "query": "janedoe", "results": []},
    ]
    cluster = corr.correlate(nodes)["clusters"][0]
    assert cluster["score"] == corr.W_LOCALPART
    assert cluster["confidence"] == "low"


def test_nodes_from_findings_keeps_pivots():
    nodes = corr.nodes_from_findings([{
        "category": "name", "query": "Jane Roe",
        "result": {"results": [], "pivots": [{"type": "username", "value": "jr",
                                               "via": "name_match"}]},
    }])
    assert nodes[0]["pivots"][0]["via"] == "name_match"


# ---- R9: accounts on a web-search hit are not the node's identifiers ----

def test_search_hit_handles_are_ignored_for_username_nodes():
    node = {"type": "username", "query": "janedoe", "results": [
        {"platform": "X", "url": "https://x.com/somebodyelse/status/1",
         "source": "web_search", "info": "contact: other@mail.com"},
        {"platform": "GitHub", "url": "https://github.com/janedoe", "source": "web_search"},
    ]}
    ids = corr._extract(node)
    assert "somebodyelse" not in ids["usernames"]
    assert "other@mail.com" not in ids["emails"]
    assert "janedoe" in ids["usernames"]


# ---- R6: values never become CLI options ----

def test_positional_arg_refuses_option_like_values():
    with pytest.raises(base.ToolError):
        base.positional_arg("--web")
    assert base.positional_arg("jane-doe") == "jane-doe"


def test_sherlock_command_separates_options():
    command = sherlock_runner._build_command("janedoe")
    assert command[-2:] == ["--", "janedoe"]


def test_username_and_email_cannot_start_with_hyphen():
    with pytest.raises(inv.InvestigationValidationError):
        inv.normalize_username("--web")
    with pytest.raises(inv.InvestigationValidationError):
        inv.normalize_email("-x@example.com")


# ---- R8: partial results are cached briefly ----

@pytest.mark.asyncio
async def test_partial_result_gets_short_ttl(monkeypatch):
    stored = {}

    async def fake_set(key, value, ttl=0):
        stored[key] = ttl

    async def fake_get(_key):
        return None

    monkeypatch.setattr(inv, "set_cached_json", fake_set)
    monkeypatch.setattr(inv, "get_cached_json", fake_get)

    async def ok():
        return 1

    async def broken():
        raise base.ToolError("down")

    async def producer(fail):
        lookups = {"A": ok()}
        if fail:
            lookups["Sherlock"] = broken()
        await inv._collect(lookups)
        return {"status": "success", "results": []}

    full = await inv._cached("k:full", producer, False)
    partial = await inv._cached("k:partial", producer, True)
    assert stored["k:full"] == inv.CACHE_TTL and "failed_sources" not in full
    assert stored["k:partial"] == inv.PARTIAL_CACHE_TTL
    assert partial["failed_sources"] == ["Sherlock"]


def test_memory_cache_is_bounded(monkeypatch):
    import asyncio
    monkeypatch.setattr(cache, "_memory", {})
    monkeypatch.setattr(cache, "MEMORY_MAX_ENTRIES", 5)

    async def fill():
        async def no_client():
            return None
        monkeypatch.setattr(cache, "get_client", no_client)
        for i in range(20):
            await cache.set_cached_json(f"k{i}", i, ttl=100 + i)
    asyncio.run(fill())
    assert len(cache._memory) == 5 and "k19" in cache._memory


# ---- R5 / 1.10 / R7: watches ----

def test_signature_sees_new_breach_but_not_follower_counts():
    base_item = {"platform": "Breaches", "url": "u", "status": "found",
                 "info": "Found in: Adobe; Followers: 10"}
    sig1 = monitor.signature_items({"results": [base_item]})
    sig2 = monitor.signature_items({"results": [{**base_item, "info": "Found in: Adobe; Followers: 99"}]})
    sig3 = monitor.signature_items({"results": [{**base_item, "info": "Found in: Adobe, LinkedIn"}]})
    assert sig1 == sig2
    assert "~1 changed" in monitor._diff_summary(sig1, sig3)


def test_signature_ignores_search_churn_and_legacy_baselines():
    assert monitor.signature_items({"results": [
        {"platform": "web", "url": "u", "source": "web_search"}]}) == []
    legacy = ["GitHub|https://github.com/x|found"]
    new = monitor.signature_items({"results": [
        {"platform": "GitHub", "url": "https://github.com/x", "status": "found", "info": "Bio: hi"}]})
    assert monitor._diff_summary(legacy, new) is None


@pytest.fixture()
def store_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CASES_DB_PATH", str(tmp_path / "cases.db"))
    import store
    importlib.reload(store)
    store.init_db()
    monkeypatch.setattr(monitor, "store", store)
    return store


@pytest.mark.asyncio
async def test_failed_source_is_not_reported_as_removed(store_mod, monkeypatch):
    w = store_mod.create_watch("w", "username", "janedoe", 60)
    gh = {"platform": "GitHub", "url": "https://github.com/janedoe", "status": "found"}
    gl = {"platform": "GitLab", "url": "https://gitlab.com/janedoe", "status": "found"}
    responses = [
        {"status": "success", "results": [gh, gl]},
        {"status": "success", "results": [gh], "failed_sources": ["Sherlock"]},
        {"status": "success", "results": [gh, gl]},
    ]

    async def fake(category, query, **_kw):
        return responses.pop(0)

    monkeypatch.setattr(monitor, "investigate", fake)
    await monitor.check_watch(store_mod.get_watch(w["id"]))
    second = await monitor.check_watch(store_mod.get_watch(w["id"]))
    assert second["status"].startswith("no change (partial")
    third = await monitor.check_watch(store_mod.get_watch(w["id"]))
    assert third["status"] == "no change"
    assert store_mod.get_watch(w["id"])["events"] == []


@pytest.mark.asyncio
async def test_overlapping_checks_log_a_change_once(store_mod, monkeypatch):
    w = store_mod.create_watch("w", "username", "janedoe", 60)
    store_mod.record_watch_check(w["id"], json.dumps([]), "baseline", None)
    stale = store_mod.get_watch(w["id"])

    async def fake(category, query, **_kw):
        return {"status": "success", "results": [
            {"platform": "GitHub", "url": "https://github.com/janedoe", "status": "found"}]}

    monkeypatch.setattr(monitor, "investigate", fake)
    first = await monitor.check_watch(stale)
    second = await monitor.check_watch(stale)  # same old baseline: a racing run
    assert first["status"] == "changed" and second["status"] == "skipped"
    assert len(store_mod.get_watch(w["id"])["events"]) == 1


def test_watch_count_is_capped(store_mod, monkeypatch):
    monkeypatch.setattr(store_mod, "MAX_WATCHES", 2)
    store_mod.create_watch("a", "domain", "a.com", 60)
    store_mod.create_watch("b", "domain", "b.com", 60)
    with pytest.raises(store_mod.CaseError):
        store_mod.create_watch("c", "domain", "c.com", 60)


# ---- R11: correlate input is bounded ----

@pytest.mark.asyncio
async def test_correlate_rejects_huge_node_lists():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/correlate", json={"nodes": [{"type": "username", "query": "a"}] * 201})
    assert resp.status_code == 400


# ---- R10: the request goes to the IP that was checked ----

def test_pinned_url_keeps_port_and_brackets_ipv6():
    from urllib.parse import urlparse
    assert net_guard._pinned(urlparse("https://a.com:443/x?y=1"), "1.2.3.4") == "https://1.2.3.4:443/x?y=1"
    assert net_guard._pinned(urlparse("http://a.com/"), "2606:4700::1") == "http://[2606:4700::1]/"


@pytest.mark.asyncio
async def test_safe_get_connects_to_validated_ip(monkeypatch):
    async def fake_check(url):
        from urllib.parse import urlparse
        return urlparse(url), "example.com", ["93.184.216.34"]

    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["host"] = request.headers["host"]
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(net_guard, "_check_url", fake_check)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await net_guard.safe_get(client, "http://example.com/page")
    assert seen == {"url": "http://93.184.216.34/page", "host": "example.com"}
    assert str(response.url) == "http://example.com/page"


# ---- 1.9: unreachable Truecaller is skipped for a while ----

@pytest.mark.asyncio
async def test_truecaller_cooldown_after_connect_error(monkeypatch):
    monkeypatch.setattr(truecaller, "_unreachable_until", 0.0)
    calls = {"n": 0}

    async def boom(self, url, **kw):
        calls["n"] += 1
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx.AsyncClient, "get", boom)
    for _ in range(2):
        with pytest.raises(truecaller.TruecallerUnavailable):
            await truecaller.scrape_truecaller("+998901234567", "uz")
    assert calls["n"] == 1
