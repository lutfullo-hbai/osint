"""10.5b: a knowledge base lists several people with the searched name; the age
the user gave picks the one person it fits, whose accounts then count as
knowledge-base evidence (like a name nobody else has)."""
import copy

import pytest

from services import agent
from services.agent_parse import parse_request
from tools import entity_intel


def target(text):
    return agent.Target(parse_request(text))


def wikidata(title, handle, born=None, human=True):
    info = "computer scientist" + (f"; Born: {born}" if born else "")
    return {"platform": "Wikidata", "title": title, "info": info}, [{"type": "username", "value": handle}], human


# ---------------- entity_intel: namesake pivots carry birth years ----------------

def test_namesake_pivots_carry_their_birth_years():
    pivots = entity_intel._grade_pivots("Ian Goodfellow", [
        wikidata("Ian Goodfellow", "goodfeli", born=1987),
        wikidata("Ian Goodfellow", "ian_virology"),
    ], other_matching_humans=2, other_births=(1950,))
    by_handle = {p["value"]: p for p in pivots}
    assert by_handle["goodfeli"] == {"type": "username", "value": "goodfeli", "via": "name_match",
                                     "born": 1987, "namesake_births": [None, 1950, None]}
    assert by_handle["ian_virology"]["born"] is None
    assert by_handle["ian_virology"]["namesake_births"] == [1987, 1950, None]


def test_unique_person_and_other_labels_are_unchanged():
    assert entity_intel._grade_pivots("Linus Torvalds", [wikidata("Linus Torvalds", "torvalds", born=1969)]) == [
        {"type": "username", "value": "torvalds", "via": "knowledge_base"}]
    # a human whose label is not the searched name gets no birth data to be confirmed by
    pivots = entity_intel._grade_pivots("Jane Roe", [wikidata("Jane Roe", "a"), wikidata("Jane Roe-Smith", "b", born=1990)],
                                        other_matching_humans=1)
    assert "born" not in {p["value"]: p for p in pivots}["b"]


@pytest.mark.asyncio
async def test_matching_humans_returns_birth_years(monkeypatch):
    def entity(label, born=None, human=True):
        claims = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5" if human else "Q11424"}}}}]}
        if born:
            claims["P569"] = [{"mainsnak": {"datavalue": {"value": {"time": f"+{born}-04-14T00:00:00Z"}}}}]
        return {"labels": {"en": {"value": label}}, "claims": claims}

    async def fake_get_json(client, url, **kwargs):
        return {"entities": {"Q1": entity("Ken Thompson", 1954), "Q2": entity("Ken Thompson"),
                             "Q3": entity("Ken Thompson", 1943, human=False), "Q4": entity("Kenneth Thompson", 1960)}}

    monkeypatch.setattr(entity_intel, "_get_json", fake_get_json)
    assert await entity_intel._matching_humans(None, "Ken Thompson", ["Q1", "Q2", "Q3", "Q4"]) == [1954, None]
    assert await entity_intel._matching_humans(None, "Ken Thompson", []) == []


@pytest.mark.asyncio
async def test_matching_humans_failure_is_one_unknown_namesake(monkeypatch):
    async def failing(client, url, **kwargs):
        raise entity_intel.ToolError("Wikimedia rate limit reached.")

    monkeypatch.setattr(entity_intel, "_get_json", failing)
    assert await entity_intel._matching_humans(None, "X", ["Q1"]) == [None]   # nobody becomes "unique"


# ---------------- agent: the age picks the person ----------------

def name_node(*pivots):
    return {"key": "name:ian goodfellow", "type": "name", "query": "Ian Goodfellow", "pivots": list(pivots)}


GOODFELI = {"type": "username", "value": "goodfeli", "via": "name_match", "born": 1987, "namesake_births": [None, 1950]}
VIROLOGY = {"type": "username", "value": "ian_virology", "via": "name_match", "born": None, "namesake_births": [1987, 1950]}


def test_the_age_picks_the_one_namesake_it_fits():
    node = name_node(GOODFELI, VIROLOGY)
    assert target("Ian Goodfellow, 39 years old, from San Francisco").confirm_by_age([node]) == 1
    assert node["pivots"][0]["via"] == "knowledge_base" and node["pivots"][0]["age_confirmed"] == 1987
    assert node["pivots"][1]["via"] == "name_match"            # no birth year: stays a namesake


def test_no_upgrade_when_another_namesake_fits_the_age_too():
    twin = {**GOODFELI, "namesake_births": [1988]}             # within a year: either could be meant
    node = name_node(twin)
    assert target("Ian Goodfellow, 39 years old").confirm_by_age([node]) == 0
    assert node["pivots"][0]["via"] == "name_match"


def test_no_upgrade_when_the_age_does_not_fit_or_was_not_given():
    node = name_node(GOODFELI)
    assert target("Ian Goodfellow, 60 years old").confirm_by_age([node]) == 0
    assert target("Ian Goodfellow from San Francisco").confirm_by_age([node]) == 0
    assert node["pivots"][0]["via"] == "name_match"


def test_only_name_records_and_name_matches_are_touched():
    username_node = {"key": "username:x", "type": "username", "pivots": [dict(GOODFELI)]}
    variant = {"type": "username", "value": "iangoodfellow", "via": "name_variant", "born": 1987}
    node = name_node(variant)
    t = target("Ian Goodfellow, 39 years old")
    assert t.confirm_by_age([username_node, node]) == 0
    assert username_node["pivots"][0]["via"] == "name_match" and node["pivots"][0]["via"] == "name_variant"


def test_cached_pivots_are_not_edited():
    cached = {"status": "success", "pivots": [dict(GOODFELI)]}       # what the name lookup cache holds
    before = copy.deepcopy(cached)
    node = name_node()
    node["pivots"] = cached["pivots"]                                 # deep_scan shares the list
    target("Ian Goodfellow, 39 years old").confirm_by_age([node])
    assert cached == before and node["pivots"][0]["via"] == "knowledge_base"


@pytest.mark.asyncio
async def test_deep_scan_follows_the_age_confirmed_account_as_knowledge_base(monkeypatch):
    from services import deep_scan

    async def name(value):
        return {"status": "success", "results": [], "count": 0, "pivots": [dict(GOODFELI), dict(VIROLOGY)]}

    async def username(value):
        return {"status": "success", "results": [], "count": 0, "pivots": []}

    monkeypatch.setitem(deep_scan._HANDLERS, "name", name)
    monkeypatch.setitem(deep_scan._HANDLERS, "username", username)
    t = target("Ian Goodfellow, 39 years old")
    scan = await deep_scan.run_deep_scan("Ian Goodfellow", "name", expand=t.expand, prepare=t.prepare)
    via = {n["query"]: n.get("via") for n in scan["nodes"] if n["type"] == "username"}
    assert via.get("goodfeli") == "knowledge_base"
    assert via.get("ian_virology", "name_match") == "name_match"
