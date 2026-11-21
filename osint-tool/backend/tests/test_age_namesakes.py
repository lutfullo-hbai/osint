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
    assert node["pivots"][0]["via"] == "age_confirmed" and node["pivots"][0]["age_confirmed"] == 1987
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
    assert cached == before and node["pivots"][0]["via"] == "age_confirmed"


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
    assert via.get("goodfeli") == "age_confirmed"
    assert via.get("ian_virology", "name_match") == "name_match"


# ---------------- M1 (QA 10.5b): age confirmation is weaker than a unique-name KB hit ----------------

def test_age_confirmed_pivot_is_weaker_than_a_curated_kb_hit():
    from services.agent import POSSIBLE_LEAD, STRONG_LEAD
    from services.correlate import B_AGE_CONFIRMED, B_KB
    from services.names import name_bits
    # a namesake picked only by the age the user gave is a lead to check, not "strong":
    # on its own it lands in [possible, strong), and even WITH the unavoidable same-name
    # bonus in rank() it must stay below strong (strong needs more, independent evidence).
    max_name_bonus = name_bits(frozenset({"aaaa", "bbbb", "cccc"}))     # the 2.5 cap
    assert B_AGE_CONFIRMED < B_KB
    assert POSSIBLE_LEAD <= B_AGE_CONFIRMED < STRONG_LEAD
    assert B_AGE_CONFIRMED + max_name_bonus < STRONG_LEAD


@pytest.mark.asyncio
async def test_wrong_namesake_with_unrecorded_target_is_not_strong(monkeypatch):
    """The real target has no birth year on Wikidata; an unrelated same-name person
    does, and it matches the age. That person is surfaced (age_confirmed) but must
    NOT be a strong lead on the age alone — only a lead to check by hand."""
    from services import deep_scan
    from services.correlate import correlate
    # the real target's birth year is unrecorded ([None]); the unrelated namesake's fits
    wrong = {"type": "username", "value": "other_person", "via": "name_match",
             "born": 1987, "namesake_births": [None]}

    async def name(value):
        return {"status": "success", "results": [], "count": 0, "pivots": [dict(wrong)]}

    async def username(value):
        res = [{"platform": "GitHub", "url": f"https://github.com/{value}", "status": "found",
                "info": "Name: Jane Common"}]
        return {"status": "success", "results": res, "count": 1, "pivots": []}

    monkeypatch.setitem(deep_scan._HANDLERS, "name", name)
    monkeypatch.setitem(deep_scan._HANDLERS, "username", username)
    t = target("Jane Common, 39 years old")
    scan = await deep_scan.run_deep_scan("Jane Common", "name", expand=t.expand, prepare=t.prepare)
    via = {n["query"]: n.get("via") for n in scan["nodes"] if n["type"] == "username"}
    assert via.get("other_person") == "age_confirmed"       # surfaced as a lead
    scan["clusters"] = correlate(scan["nodes"])["clusters"]
    cands, _ = agent.rank(scan, t, set())
    picked = next((c for c in cands if any(m["query"] == "other_person" for m in c["members"])), None)
    assert picked is not None and picked["level"] != "strong"   # a lead, not a confident identification


# ---------------- M1 negative (QA): clash with the user's age/name is never "strong" ----------------

def test_knowledge_base_identity_at_a_conflicting_age_is_not_strong():
    """The famous person really is found (unique-name KB, high score), but the user gave
    an age 30 years off. The account is real, yet it is not 'the person you are looking
    for': cap at possible with the conflict shown (negative-case goal)."""
    # the cap keys on the user-facing age/name conflict messages, not on within-cluster noise
    assert any("born 1955, but the person you describe".startswith(p) for p in agent._TARGET_CONFLICT_PREFIXES)
    assert any("different name: Ann".startswith(p) for p in agent._TARGET_CONFLICT_PREFIXES)
    assert not any("different stated locations: X".startswith(p) for p in agent._TARGET_CONFLICT_PREFIXES)


@pytest.mark.asyncio
async def test_rank_caps_a_conflicting_kb_identity_at_possible(monkeypatch):
    from services import deep_scan
    from services.correlate import correlate

    async def name(value):
        # a knowledge-base hit whose profile shows a birth year that conflicts with the age
        return {"status": "success",
                "results": [{"platform": "Wikidata", "url": "https://www.wikidata.org/wiki/Q80",
                             "status": "found", "info": "Name: Tim Person; Born: 1955"}],
                "count": 1, "pivots": [{"type": "username", "value": "timperson", "via": "knowledge_base"}]}

    async def username(value):
        return {"status": "success",
                "results": [{"platform": "GitHub", "url": f"https://github.com/{value}", "status": "found",
                             "info": "Name: Tim Person; Born: 1955"}],
                "count": 1, "pivots": []}

    monkeypatch.setitem(deep_scan._HANDLERS, "name", name)
    monkeypatch.setitem(deep_scan._HANDLERS, "username", username)
    t = target("Tim Person, 25 years old")           # ~2001, conflicts with 1955
    scan = await deep_scan.run_deep_scan("Tim Person", "name", expand=t.expand, prepare=t.prepare)
    scan["clusters"] = correlate(scan["nodes"])["clusters"]
    cands, _ = agent.rank(scan, t, set())
    assert cands and cands[0]["level"] != "strong"   # real identity, wrong age -> not strong
    assert any("born" in c.lower() for c in cands[0]["contradictions"])
