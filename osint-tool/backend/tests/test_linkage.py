"""Faza 2: cross-script names, evidence weights, contradictions, gold set."""
import json
import os

import pytest

from services import correlate as corr
from services import deep_scan
from services import names
from scripts.eval_linkage import evaluate

GOLD = os.path.join(os.path.dirname(__file__), "fixtures", "linkage_gold.json")


@pytest.mark.parametrize("a,b", [
    ("Lutfullo Abdubaniyev", "Лутфулло Абдубаниев"),
    ("Abdubaniyev Lutfullo", "lutfullo abdubaniev"),
    ("Lutfullo Abdubaniyev", "Лутфулла Абдубаниев"),
    ("Shavkat Mirziyoyev", "Шавкат Мирзиёев"),
    ("Shavkat Miromonovich Mirziyoyev", "Shavkat Mirziyoyev"),
    ("Xo'jayev Bobur", "Ходжаев Бобур"),
    ("G‘ulomov Anvar", "Гуломов Анвар"),
])
def test_same_name_across_scripts_and_spellings(a, b):
    assert names.names_match(a, b)


def test_different_names_do_not_match():
    assert not names.names_match("Aziz Karimov", "Aziz Rahimov")
    assert not names.names_match("Aziz", "Aziz")  # one token is not a full name


def test_common_names_weigh_less():
    common = names.name_bits(names.names_match("Aziz Karimov", "Азиз Каримов"))
    rare = names.name_bits(names.names_match("Lutfullo Abdubaniyev", "Лутфулло Абдубаниев"))
    assert common < rare


def test_places_across_scripts():
    assert not names.places_conflict("Toshkent", "Ташкент")
    assert not names.places_conflict("Namangan", "Наманган, Uzbekistan")
    assert names.places_conflict("Tashkent", "London, UK")


def test_username_variants():
    ideas = names.username_variants("Лутфулло Абдубаниев", birth_year=2007)
    assert "lutfullo.abdubaniev" in ideas and "lutfulloabdubaniev07" in ideas
    assert names.username_variants("Madonna") == []


def test_handle_bits_rare_vs_common():
    assert corr.handle_bits("karimov") < corr.handle_bits("qodirov1994")
    assert corr.handle_bits("abcd") < corr.handle_bits("zephyrquill")


def test_birth_year_conflict_vetoes_a_knowledge_base_link():
    nodes = [
        {"key": "name:r", "type": "name", "query": "Rustam Ergashev", "results": [
            {"platform": "Wikidata", "url": "https://www.wikidata.org/wiki/Q1", "info": "Born: 1969-05-01"}],
         "pivots": [{"type": "username", "value": "rergashev", "via": "knowledge_base"}]},
        {"key": "username:rergashev", "type": "username", "query": "rergashev", "results": [
            {"platform": "GitHub", "url": "https://github.com/rergashev", "info": "Born: 1995"}]},
    ]
    out = corr.correlate(nodes)
    assert out["cluster_count"] == 2
    hub = next(c for c in out["clusters"] if "name:r" in c["members"])
    assert "different birth years" in hub["candidates"][0]["reason"]


def test_guessed_username_is_only_a_candidate():
    nodes = [
        {"key": "name:malika sobirova", "type": "name", "query": "Malika Sobirova", "results": []},
        {"key": "username:malikasobirova", "type": "username", "query": "malikasobirova",
         "parent": "name:malika sobirova", "via": "name_variant",
         "results": [{"platform": "GitHub", "url": "https://github.com/malikasobirova",
                      "info": "Name: Malika Sobirova"}]},
    ]
    out = corr.correlate(nodes)
    assert out["cluster_count"] == 2
    hub = next(c for c in out["clusters"] if "name:malika sobirova" in c["members"])
    assert "guessed from the name" in hub["candidates"][0]["reason"]


def test_deep_scan_follows_at_most_two_guessed_usernames():
    result = {"pivots": [{"type": "username", "value": "kb", "via": "knowledge_base"}],
              "username_ideas": ["a1", "a2", "a3", "a4"]}
    out = deep_scan._followable_pivots(deep_scan._node_pivots(result))
    assert out[0]["value"] == "kb"
    assert [p["value"] for p in out if p["via"] == "name_variant"] == ["a1", "a2"]


def test_gold_set_no_false_merges_and_good_recall():
    with open(GOLD, encoding="utf-8") as fh:
        cases = json.load(fh)
    assert len(cases) >= 20
    result = evaluate(cases)
    misses = [(k, c["id"]) for k, c in result["misses"]]
    assert result["precision"] == 1.0, misses   # a false merge is the costly error
    assert result["recall"] >= 0.85, misses
