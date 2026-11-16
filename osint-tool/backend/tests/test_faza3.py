"""Faza 3: SearXNG + fallback, Subfinder, published emails, Maigret DB,
Wayback first-seen dates, source health."""
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import main
from routers import sources as sources_router
from tools import base, domain_emails, maigret_db, profile_history, public_search, subfinder_runner
from tools.base import ToolError


# ---- 3.1 search backends ----

def test_parse_searxng():
    data = {"results": [
        {"url": "https://github.com/jane", "title": "jane", "content": "Jane's code", "engines": ["brave"]},
        {"url": "javascript:alert(1)", "title": "x"},
    ]}
    out = public_search.parse_searxng(data, 10)
    assert len(out) == 1
    assert out[0]["platform"] == "GitHub" and out[0]["source"] == "web_search"
    assert out[0]["engines"] == ["brave"]


@pytest.mark.asyncio
async def test_search_falls_back_to_next_backend(monkeypatch):
    calls = []

    async def broken(_b):
        calls.append("first")
        raise ToolError("rate limited")

    async def works(_b):
        calls.append("second")
        return [{"url": "https://x.com/a"}]

    monkeypatch.setattr(public_search, "_providers", lambda _n: [("A", broken), ("B", works)])
    out = await public_search.search_public(["q"])
    assert out == [{"url": "https://x.com/a"}] and calls == ["first", "second"]


@pytest.mark.asyncio
async def test_search_reports_when_every_backend_fails(monkeypatch):
    async def broken(_b):
        raise ToolError("down")

    monkeypatch.setattr(public_search, "_providers", lambda _n: [("A", broken), ("B", broken)])
    with pytest.raises(ToolError) as exc:
        await public_search.search_public(["q"])
    assert "A: down" in str(exc.value) and "B: down" in str(exc.value)


@pytest.mark.asyncio
async def test_search_with_no_hits_is_empty_not_an_error(monkeypatch):
    async def empty(_b):
        return []

    monkeypatch.setattr(public_search, "_providers", lambda _n: [("A", empty)])
    assert await public_search.search_public(["q"]) == []


def test_searxng_is_preferred_over_duckduckgo(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setenv("SEARXNG_URL", "http://searxng:8080")
    assert [label for label, _ in public_search._providers(5)] == ["SearXNG", "DuckDuckGo"]


# ---- 3.6 Subfinder ----

def test_subfinder_jsonl_keeps_only_the_domain():
    stdout = "\n".join([
        json.dumps({"host": "api.example.com", "sources": ["crtsh", "anubis"]}),
        json.dumps({"host": "*.dev.example.com", "source": "alienvault"}),
        json.dumps({"host": "evil.com"}),
        json.dumps({"host": "notexample.com"}),
        "garbage",
    ])
    hosts, sources = subfinder_runner.parse_jsonl(stdout, "example.com")
    assert hosts == {"api.example.com", "dev.example.com"}
    assert {"crtsh", "anubis", "alienvault"} <= sources


# ---- 3.7 published emails ----

def test_domain_emails_only_from_the_domain_and_typed():
    items = [
        {"url": "https://acme.uz/contact", "title": "Contact", "info": "Write to info@acme.uz or a.karimov@acme.uz; partner x@other.uz"},
        {"url": "https://news.uz/a", "title": "Story", "info": "reach hr@mail.acme.uz"},
    ]
    out = domain_emails.extract_domain_emails(items, "acme.uz")
    emails = {e["email"]: e for e in out}
    assert set(emails) == {"info@acme.uz", "a.karimov@acme.uz", "hr@mail.acme.uz"}
    assert "role or list address" in emails["info@acme.uz"]["info"]
    assert "looks personal" in emails["a.karimov@acme.uz"]["info"]
    assert domain_emails.address_kind("security-announce") == "role or list address"
    assert domain_emails.address_kind("lxml") == "address"
    assert emails["a.karimov@acme.uz"]["url"] == "https://acme.uz/contact"


@pytest.mark.asyncio
async def test_domain_emails_skip_shared_mail_providers(monkeypatch):
    async def never(*_a, **_k):
        raise AssertionError("must not search gmail.com")

    monkeypatch.setattr(domain_emails, "search_public", never)
    assert await domain_emails.find_domain_emails("gmail.com") == []


# ---- 3.2 / 3.3 Maigret database ----

def test_customize_promotes_uzbek_sites_and_merges_extras():
    db = {"sites": {
        "mover.uz": {"url": "https://mover.uz/channel/{username}", "urlMain": "https://mover.uz/"},
        "Forum": {"tags": ["uz"], "alexaRank": 900000},
        "Old": {"tags": ["uz"], "disabled": True},
        "Global": {"urlMain": "https://example.com/", "alexaRank": 10},
    }}
    out, promoted = maigret_db.customize(db, {"NewSite.uz": {"urlMain": "https://new.uz/"}})
    assert promoted == ["Forum", "NewSite.uz", "mover.uz"]
    assert out["sites"]["Forum"]["alexaRank"] == maigret_db.PROMOTED_RANK
    assert "alexaRank" not in out["sites"]["Old"]          # disabled stays untouched
    assert out["sites"]["Global"]["alexaRank"] == 10


def test_build_db_writes_a_copy(tmp_path, monkeypatch):
    src = tmp_path / "bundled.json"
    src.write_text(json.dumps({"sites": {"x.uz": {"urlMain": "https://x.uz/"}}, "engines": {}, "tags": []}))
    monkeypatch.setattr(maigret_db, "bundled_db_path", lambda: str(src))
    dest = tmp_path / "data" / "db.json"
    assert maigret_db.build_db(str(dest)) == ["x.uz"]
    assert json.loads(dest.read_text())["sites"]["x.uz"]["alexaRank"] == maigret_db.PROMOTED_RANK
    assert json.loads(src.read_text())["sites"]["x.uz"].get("alexaRank") is None  # original untouched


@pytest.mark.asyncio
async def test_run_command_feeds_stdin():
    out = await base.run_command(["cat"], input_text="y\n")
    assert out["stdout"] == "y\n"


# ---- 3.4 Wayback first-seen ----

def test_first_snapshot_parsing():
    data = {"archived_snapshots": {"closest": {"available": True, "timestamp": "20130726101500",
                                               "url": "http://web.archive.org/web/2013/x"}}}
    assert profile_history._first_snapshot(data) == ("2013-07-26", "http://web.archive.org/web/2013/x")
    assert profile_history._first_snapshot({"archived_snapshots": {}}) is None


@pytest.mark.asyncio
async def test_annotate_first_archived_only_strong_hits(monkeypatch):
    async def fake_get(self, url, params=None, **kw):
        return httpx.Response(200, json={"archived_snapshots": {"closest": {
            "available": True, "timestamp": "20150101000000", "url": "http://web.archive.org/x"}}})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    strong = {"url": "https://github.com/jane", "confidence": "high", "info": "Bio: hi"}
    weak = {"url": "https://site.io/jane", "confidence": "low", "sources": ["maigret"]}
    await profile_history.annotate_first_archived([strong, weak])
    assert strong["first_archived"] == "2015-01-01" and "First archived: 2015-01-01" in strong["info"]
    assert "first_archived" not in weak


# ---- 3.5 source health ----

@pytest.mark.asyncio
async def test_sources_health_endpoint(monkeypatch):
    async def ok(_client):
        return {"ok": True, "detail": "fine"}

    monkeypatch.setattr(sources_router, "_searxng", ok)
    monkeypatch.setattr(sources_router, "_github", ok)
    monkeypatch.setenv("GITHUB_TOKEN", "secret-value")
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/sources/health")
    data = resp.json()
    assert resp.status_code == 200
    assert {"Web search", "SearXNG", "GitHub API", "Maigret", "Subfinder", "Truecaller"} <= set(data["sources"])
    assert data["keys"]["GITHUB_TOKEN"] is True
    assert "secret-value" not in resp.text      # only "set / not set", never the value
