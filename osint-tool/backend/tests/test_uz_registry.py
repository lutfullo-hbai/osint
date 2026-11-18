"""Faza 3b.5: Uzbek official registers (data.egov.uz) in company and name search."""
import pytest

from services import investigate as inv
from tools import uz_registry as uz

TAX_ROWS = [
    {"nomer": "1", "Viloyat": "Andijon viloyati", "Tuman": "Andijon shahar", "STIR": "201728764",
     "Korxonanomi": "АНДИЖОН ВИЛОЯТИ КИРГИЗ МИЛЛИЙ МАДАНИЙ МАРКАЗИ"},
    {"nomer": "2", "Viloyat": "Toshkent shahri", "Tuman": "Yunusobod", "STIR": "306939961",
     "Korxonanomi": "\"TYPE MAKER\" MCHJ"},
]
BAD_ROWS = [{"Tashkilot": "“TYPE MAKER” MCHJ", "STIR": "306939961", "Hudud": "Qoraqalpog‘iston",
             "KiritilganSana": "2025-09-11", "ChiqarilishSanasi": "2027-09-10"}]
BOARD_ROWS = [{"Korxonanomi": "«Ўзбекнефтгаз» АЖ", "FISh": "Normatov Behzod Rahmatullayevich",
               "Lavozimi": "Kuzatuv kengashi a'zosi"}]
AUTO_ROWS = [{"TASHKILOT_NOMI": "Navoiy kon-metallurgiya kombinati AJ", "STIR_RAQAMI": "200000000",
              "HUDUD": "Navoiy"}]


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "uz.db")
    uz.store_dataset("tax_entities", uz.rows_to_records("tax_entities", TAX_ROWS), False, path)
    uz.store_dataset("unscrupulous_suppliers", uz.rows_to_records("unscrupulous_suppliers", BAD_ROWS), False, path)
    uz.store_dataset("soe_boards", uz.rows_to_records("soe_boards", BOARD_ROWS), False, path)
    uz.store_dataset("soe_national", uz.rows_to_records("soe_national", AUTO_ROWS), False, path)
    return path


def test_org_tokens_drop_legal_forms():
    assert uz.org_tokens('"TYPE MAKER" MCHJ') == ["type", "maker"]
    assert uz.org_tokens("ООО Hamkor") == uz.org_tokens("Hamkor MChJ") == ["hamkor"]
    assert uz.org_tokens("«Ўзбекнефтгаз» АЖ") == uz.org_tokens("O‘zbekneftgaz AJ")


def test_search_by_stir_finds_every_register(db):
    hits = uz.search_org("306939961", path=db)
    assert {h["dataset"] for h in hits} == {"tax_entities", "unscrupulous_suppliers"}


def test_search_by_name_across_scripts_and_forms(db):
    assert [h["dataset"] for h in uz.search_org("Type Maker", path=db)]
    cyr = uz.search_org("Andijon viloyati qirgiz milliy madaniy markazi", path=db)
    assert cyr and cyr[0]["stir"] == "201728764"          # Latin query, Cyrillic record
    assert uz.search_org("MCHJ", path=db) == []           # legal form alone is not a name


def test_unscrupulous_supplier_is_flagged(db):
    hit = next(h for h in uz.search_org("306939961", path=db) if h["dataset"] == "unscrupulous_suppliers")
    result = uz.to_result(hit)
    assert result["status"] == "warning" and "unscrupulous supplier" in result["info"]
    assert result["url"].startswith("https://data.egov.uz/data/")


def test_person_with_a_role_in_a_register(db):
    hits = uz.search_person("Behzod Normatov", path=db)
    assert len(hits) == 1 and hits[0]["role"] == "Kuzatuv kengashi a'zosi"
    info = uz.to_result(hits[0], as_person=True)["info"]
    assert "Person: Normatov Behzod Rahmatullayevich (Kuzatuv kengashi a'zosi)" in info
    assert "confirm it is the same person" in info
    assert uz.search_person("Behzod Karimov", path=db) == []


def test_company_hit_lists_the_registered_person(db):
    hit = uz.search_org("Ўзбекнефтгаз", path=db)[0]
    assert "Listed person: Normatov Behzod Rahmatullayevich (Kuzatuv kengashi a'zosi)" in uz.to_result(hit)["info"]


def test_auto_detected_columns(db):
    hits = uz.search_org("Navoiy kon-metallurgiya kombinati", path=db)
    assert hits and hits[0]["stir"] == "200000000" and hits[0]["region"] == "Navoiy"


@pytest.mark.asyncio
async def test_company_search_survives_gleif_outage(db, monkeypatch):
    async def gleif_down(_q):
        raise inv.ToolError("GLEIF is unreachable")
    monkeypatch.setattr(inv, "run_company_search", gleif_down)
    monkeypatch.setattr(uz, "DB_PATH", db)
    monkeypatch.setattr(uz.search_org, "__defaults__", (db,))
    out = await inv._investigate_company("306939961")
    assert out["count"] == 2 and out["results"][0]["source"] == "uz_register"
