"""3b.5c: GLEIF subsidiaries, UK Companies House, GDELT limits/cache."""
import httpx
import pytest

import cache
from tools import company_intel as ci


def _record(lei, name):
    return {"attributes": {"lei": lei, "entity": {"legalName": {"name": name},
            "legalAddress": {"country": "UZ"}, "status": "ACTIVE"}, "registration": {}}}


@pytest.mark.asyncio
async def test_children_lists_subsidiaries_and_pivots():
    def handler(request):
        assert request.url.path.endswith("/direct-children")
        return httpx.Response(200, json={"data": [_record("A" * 20, "Child One LLC")],
                                         "meta": {"pagination": {"total": 12}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results, pivots = await ci._children(client, "B" * 20)
    assert results[0]["platform"] == "Subsidiary (GLEIF)"
    assert pivots == [{"type": "company", "value": "Child One LLC"}]
    assert "12 direct subsidiaries" in results[-1]["info"]


@pytest.mark.asyncio
async def test_companies_house_needs_a_key(monkeypatch):
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    with pytest.raises(ci.NotConfigured):
        await ci.companies_house_search(None, "Acme")


@pytest.mark.asyncio
async def test_companies_house_company_and_officers(monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "free-key")

    def handler(request):
        assert request.headers["authorization"].startswith("Basic ")
        if request.url.path == "/search/companies":
            return httpx.Response(200, json={"items": [{"title": "ACME LTD", "company_number": "01234567",
                                                        "company_status": "active", "date_of_creation": "2001-02-03",
                                                        "address_snippet": "1 High St, London"}]})
        return httpx.Response(200, json={"items": [
            {"name": "DOE, Jane", "officer_role": "director", "appointed_on": "2010-01-01"},
            {"name": "OLD, Bob", "officer_role": "secretary", "resigned_on": "2015-01-01"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await ci.companies_house_search(client, "Acme")
    assert "Company number: 01234567" in out[0]["info"]
    assert "DOE, Jane (director, since 2010-01-01)" in out[0]["info"]
    assert "OLD, Bob" not in out[0]["info"]          # resigned officers left out


@pytest.mark.asyncio
async def test_gdelt_respects_its_limit_and_caches(monkeypatch):
    monkeypatch.setattr(cache, "_memory", {})

    async def no_client():
        return None
    monkeypatch.setattr(cache, "get_client", no_client)
    monkeypatch.setattr(ci, "_gdelt_last", 0.0)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, headers={"content-type": "application/json"},
                              json={"articles": [{"seendate": "20261101T000000Z", "domain": "kun.uz",
                                                  "title": "Acme news"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await ci.gdelt_news(client, "Acme")
        again = await ci.gdelt_news(client, "Acme")          # served from cache
        with pytest.raises(ci.ToolError, match="limit was just used"):
            await ci.gdelt_news(client, "Other Co")           # limit just used
    assert first == again and calls["n"] == 1
