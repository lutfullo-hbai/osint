"""10.5b: places are compared as agree / conflict / unknown, and a different
town alone no longer makes a lead weak."""
import pytest

from services import agent
from services.agent_parse import parse_request
from services.names import place_relation, places_conflict


@pytest.mark.parametrize("a, b, relation", [
    ("Los Angeles", "United States", "agree"),              # teorth: a known town inside the country
    ("San Francisco", "USA", "agree"),
    ("Mountain View, CA", "United States", "agree"),
    ("Mountain View", "California", "unknown"),             # states are not in the gazetteer
    ("Ann Arbor", "United States", "unknown"),              # a town we cannot place
    ("Portland, OR", "Italy", "conflict"),                  # 10.1 QA case still holds
    ("Portland", "Seattle", "conflict"),                    # one country does not make two towns agree
    ("Tashkent", "Uzbekistan", "agree"),
    ("Paris, Texas", "France", "conflict"),                 # a stated state wins over the gazetteer
    ("Los Angeles, United States", "USA", "agree"),
    ("Namangan", "Наманган, Uzbekistan", "agree"),
    ("Toshkent", "Ташкент", "agree"),
    ("Tashkent", "London, UK", "conflict"),
    ("United Kingdom", "United States", "conflict"),        # used to agree through "united"
    ("New York", "New Delhi", "conflict"),                  # used to agree through "new"
    ("Montréal, Québec", "Mountain View", "conflict"),
    ("California", "Texas", "conflict"),
    ("California", "United States", "agree"),
    ("Scotland", "United Kingdom", "agree"),
    ("Paris, France", "Germany", "conflict"),
    ("", "Tashkent", "unknown"),
])
def test_place_relation(a, b, relation):
    assert place_relation(a, b) == relation
    assert place_relation(b, a) == relation                 # symmetric
    assert places_conflict(a, b) == (relation == "conflict")


def target(text):
    return agent.Target(parse_request(text))


def test_a_town_inside_the_stated_country_agrees():
    check = target("Terence Tao, 51 years old, from United States").place_check({"Los Angeles"})
    assert check[0] == agent.B_PLACE_AGREE
    assert target("Terence Tao, 51 years old, from United States").place_check({"Ann Arbor"}) is None


def test_a_clearly_different_place_still_counts_against():
    check = target("Ali Valiyev, 30 years old, from Tashkent").place_check({"London, UK"})
    assert check[0] == agent.B_PLACE_CONFLICT
    assert agent._hard([check[1]]) == []                    # a place mismatch is a soft conflict


def test_soft_conflicts_lower_the_score_but_do_not_force_weak():
    town = target("Ian Goodfellow, 39 years old, from San Francisco").place_check({"Mountain View"})[1]
    assert agent._level(3.5, [town, "different stated locations: Montréal, Québec; Mountain View"]) == "possible"
    assert agent._level(3.5, [town, "born 1950, but the person you describe was born ~1987"]) == "weak"
    assert agent._level(3.5, ["different birth years: 1950, 1987"]) == "weak"
    assert agent._level(2.0, [town]) == "weak"              # a low score stays weak anyway
    assert agent._level(6.5, ["different stated names"]) == "strong"
