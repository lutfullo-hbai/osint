"""Faza 3b.1: local sanctions/PEP index from official free lists."""
import pytest

from tools import entity_intel
from tools import sanctions_index as si

UN_XML = b"""<?xml version="1.0"?><CONSOLIDATED_LIST><INDIVIDUALS>
<INDIVIDUAL><DATAID>1</DATAID><FIRST_NAME>ERIC</FIRST_NAME><SECOND_NAME>BADEGE</SECOND_NAME>
<UN_LIST_TYPE>DRC</UN_LIST_TYPE><REFERENCE_NUMBER>CDi.001</REFERENCE_NUMBER>
<NATIONALITY><VALUE>Congo</VALUE></NATIONALITY>
<INDIVIDUAL_ALIAS><QUALITY>Good</QUALITY><ALIAS_NAME>Erik Badege</ALIAS_NAME></INDIVIDUAL_ALIAS>
<INDIVIDUAL_DATE_OF_BIRTH><TYPE_OF_DATE>EXACT</TYPE_OF_DATE><YEAR>1971</YEAR></INDIVIDUAL_DATE_OF_BIRTH>
</INDIVIDUAL></INDIVIDUALS><ENTITIES>
<ENTITY><DATAID>2</DATAID><FIRST_NAME>ACME TRADING LLC</FIRST_NAME><UN_LIST_TYPE>DPRK</UN_LIST_TYPE>
<REFERENCE_NUMBER>KPe.1</REFERENCE_NUMBER></ENTITY></ENTITIES></CONSOLIDATED_LIST>"""

OFAC_XML = b"""<?xml version="1.0"?>
<sdnList xmlns="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/XML">
<sdnEntry><uid>35096</uid><firstName>Vladimir Vladimirovich</firstName><lastName>PUTIN</lastName>
<sdnType>Individual</sdnType><programList><program>RUSSIA-EO14024</program></programList>
<akaList><aka><uid>9</uid><type>a.k.a.</type><category>weak</category><firstName>Vova</firstName><lastName>P</lastName></aka></akaList>
<nationalityList><nationality><uid>1</uid><country>Russia</country></nationality></nationalityList>
<dateOfBirthList><dateOfBirthItem><uid>2</uid><dateOfBirth>07 Oct 1952</dateOfBirth></dateOfBirthItem></dateOfBirthList>
</sdnEntry>
<sdnEntry><uid>7</uid><lastName>YO JONG KIM</lastName><sdnType>Individual</sdnType></sdnEntry>
</sdnList>"""

EU_XML = """<?xml version="1.0" encoding="UTF-8"?>
<export xmlns="http://eu.europa.ec/fpi/fsd/export">
<sanctionEntity euReferenceNumber="EU.1.1" logicalId="1">
<regulation programme="RUS"/>
<subjectType code="person" classificationCode="P"/>
<nameAlias wholeName="Влади́мир Влади́мирович ПУ́ТИН" strong="true"/>
<citizenship countryDescription="RUSSIAN FEDERATION"/>
<birthdate year="1952"/>
</sanctionEntity></export>""".encode()

UK_CSV = (
    "Report Date: 17-Nov-2026\n"
    "Unique ID,Name 6,Name 1,Name 2,Name type,Alias strength,Name non-latin script,Regime Name,"
    "Designation Type,D.O.B,Nationality(/ies)\n"
    "RUS0001,PUTIN,Vladimir,Vladimirovich,Primary Name,,,Russia,Individual,07/10/1952,Russia\n"
    "RUS0001,PUTIN,Vova,,Alias,Weak,,Russia,Individual,07/10/1952,Russia\n"
    "AFG0001,MONEY EXCHANGE,,,Primary Name,,,Afghanistan,Entity,,\n"
).encode()


def test_parsers_read_each_official_format():
    un = si.parse_un(UN_XML)
    assert {e["kind"] for e in un} == {"person", "entity"}
    eric = next(e for e in un if e["kind"] == "person")
    assert eric["years"] == [1971] and ("Erik Badege", True, False) in eric["names"]

    ofac = si.parse_ofac(OFAC_XML)
    putin = ofac[0]
    assert putin["names"][0] == ("Vladimir Vladimirovich PUTIN", True, True)
    assert ("Vova P", False, False) in putin["names"]          # weak a.k.a. kept but marked
    assert putin["years"] == [1952] and putin["programs"] == ["RUSSIA-EO14024"]

    eu = si.parse_eu(EU_XML)
    assert eu[0]["kind"] == "person" and eu[0]["years"] == [1952]

    uk = si.parse_uk(UK_CSV)
    by_id = {e["ext_id"]: e for e in uk}
    assert set(by_id) == {"RUS0001", "AFG0001"}                # report-date line skipped
    assert len(by_id["RUS0001"]["names"]) == 2                 # rows grouped per Unique ID
    assert by_id["AFG0001"]["kind"] == "entity"


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "sanctions.db")
    si.store_source("ofac", si.parse_ofac(OFAC_XML), "a", "u", path)
    si.store_source("eu", si.parse_eu(EU_XML), "b", "u", path)
    si.store_source("uk", si.parse_uk(UK_CSV), "c", "u", path)
    return path


def test_search_matches_across_scripts(db):
    for query in ("Vladimir Putin", "Владимир Путин", "Putin Vladimir"):
        sources = {h["source"] for h in si.search(query, path=db)}
        assert sources == {"ofac", "eu", "uk"}, query


def test_birth_year_vetoes_and_confirms(db):
    assert si.search("Vladimir Putin", birth_year=1990, path=db) == []
    assert all(h["strength"] == "strong" for h in si.search("Vladimir Putin", birth_year=1952, path=db))


def test_every_word_of_the_shorter_name_must_match(db):
    assert si.search("Kim Jong Un", path=db) == []        # not "YO JONG KIM"
    assert si.search("Putin", path=db) == []              # one word is never enough


def test_store_replaces_a_source(db):
    si.store_source("ofac", [], "z", "u", db)
    assert {h["source"] for h in si.search("Vladimir Putin", path=db)} == {"eu", "uk"}
    assert si.source_status(db)["ofac"]["records"] == 0


def test_result_never_claims_identity(db):
    result = si.to_result(si.search("Vladimir Putin", path=db)[0])
    assert result["status"] == "possible match"
    assert "VERIFY: a name match is not proof of identity" in result["info"]
    assert "Born:" not in result["info"]      # must not read as the searched person's facts


def test_pep_parsing():
    payload = {"results": {"bindings": [{
        "p": {"value": "http://www.wikidata.org/entity/Q1"},
        "position": {"value": "President of Uzbekistan"},
        "from": {"value": "2016-12-14T00:00:00Z"},
        "born": {"value": "1957-07-24T00:00:00Z"},
        "names": {"value": "Shavkat Mirziyoyev|Шавкат Мирзиёев"},
    }]}}
    peps = si.parse_peps(payload, "UZ")
    assert peps[0]["years"] == [1957] and "President of Uzbekistan (2016–)" in peps[0]["note"]
    assert peps[0]["url"] == "https://www.wikidata.org/wiki/Q1"


@pytest.mark.asyncio
async def test_sanctions_check_uses_local_index_without_any_key(db, monkeypatch):
    monkeypatch.delenv("OPENSANCTIONS_API_KEY", raising=False)
    monkeypatch.setattr(si, "DB_PATH", db)
    monkeypatch.setattr(si.search, "__defaults__", (None, db))
    out = await entity_intel.run_sanctions_check("Vladimir Putin")
    assert len(out["results"]) == 3 and out["warnings"] == []
