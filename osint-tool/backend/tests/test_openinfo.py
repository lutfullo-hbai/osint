"""openinfo.uz on-demand lookups (corporate disclosure portal)."""
import pytest

from services import investigate as inv
from tools import openinfo

ORG = {
    "id": 735, "inn": 200837914, "full_name_text": "\"O'zbekneftgaz\" Aksiyadorlik jamiyati",
    "exchange_ticket_name": "UNGS", "address": "Toshkent sh., Istiqlol 21", "email": "info@ung.uz",
    "web_site": "https://www.ung.uz/", "status_from_stat_uz": "active",
    "detailinfo": {"director_name": "Sanginov Abdug'ani", "accountant_name": "Karimov Aziz",
                   "responsible_officer_name": ""},
}


def test_query_variants_add_uzbek_latin_for_cyrillic():
    variants = openinfo.query_variants("Ўзбекнефтгаз")
    assert variants[0] == "Ўзбекнефтгаз" and "O'zbekneftgaz" in variants
    assert openinfo.query_variants("O‘zbekneftgaz") == ["O‘zbekneftgaz", "O'zbekneftgaz"]


def test_to_result_shows_disclosed_management_and_site_pivot():
    result, pivots = openinfo.to_result(ORG)
    assert "Director: Sanginov Abdug'ani" in result["info"] and "STIR: 200837914" in result["info"]
    assert "Disclosure officer" not in result["info"]          # empty fields are left out
    assert result["url"] == "https://openinfo.uz/ru/organizations/735"
    assert pivots == [{"type": "domain", "value": "ung.uz", "via": "official_register"}]


@pytest.mark.asyncio
async def test_lookup_tries_latin_variant_then_fetches_detail(monkeypatch):
    calls = []

    async def fake_get(path, params=None):
        calls.append((path, (params or {}).get("search")))
        if path.endswith("/organizations/"):
            return {"results": [{"id": 735}]} if params["search"] == "O'zbekneftgaz" else {"results": []}
        return ORG

    monkeypatch.setattr(openinfo, "_get", fake_get)
    out = await openinfo.lookup("Ўзбекнефтгаз")
    assert [c[1] for c in calls[:2]] == ["Ўзбекнефтгаз", "O'zbekneftgaz"]
    assert calls[-1][0] == "/api/v2/organizations/organizations/735/"
    assert len(out["results"]) == 1 and out["pivots"][0]["value"] == "ung.uz"


@pytest.mark.asyncio
async def test_company_search_puts_disclosure_first(monkeypatch):
    async def gleif(_q):
        return {"results": [{"platform": "Company (GLEIF)", "status": "found"}], "pivots": []}

    async def disclosure(_q):
        result, pivots = openinfo.to_result(ORG)
        return {"results": [result], "pivots": pivots}

    monkeypatch.setattr(inv, "run_company_search", gleif)
    monkeypatch.setattr(inv.openinfo, "lookup", disclosure)
    monkeypatch.setattr(inv.uz_registry, "search_org", lambda _q: [])
    out = await inv._investigate_company("O'zbekneftgaz")
    assert out["results"][0]["platform"].startswith("openinfo.uz")
    assert {"type": "domain", "value": "ung.uz", "via": "official_register"} in out["pivots"]
