"""ROADMAP 10.3: the accuracy scorer (scripts/eval_agent.py) and the case files."""
import json
import os

import pytest

from scripts import eval_agent as ev
from scripts import eval_cases_wikidata as wd

CASES = os.path.join(os.path.dirname(__file__), "..", "eval", "agent_cases.public.jsonl")


def cand(label, level, urls, set_aside=()):
    return {"label": label, "level": level,
            "fields": {"profiles": [{"value": "x", "sources": [{"platform": "p", "url": u} for u in urls]}]},
            "contacts": [], "set_aside": [{"url": u} for u in set_aside]}


def test_urls_are_compared_loosely():
    assert ev.norm_url("https://www.GitHub.com/Torvalds/") == ev.norm_url("http://github.com/torvalds")
    assert ev.norm_url("") == "" and ev.norm_url("not a url") == ""


def test_rank_level_false_strong_and_wrong_set_aside():
    case = {"id": "t", "expect": ["https://github.com/torvalds"]}
    result = {"candidates": [cand("Namesake", "strong", ["https://vk.com/x"]),
                             cand("Linus", "possible", ["https://github.com/Torvalds"]),
                             cand("Other", "weak", ["https://x.com/y"], set_aside=["https://github.com/torvalds/"])],
              "scan": {"nodes": [{"unchecked": ["GitHub"]}]}}
    row = ev.score_case(case, result)
    assert row["rank"] == 2 and row["level"] == "possible"
    assert row["false_strong"] == ["Namesake"]
    assert row["wrongly_set_aside"] == ["github.com/torvalds"]
    assert row["unchecked"] == ["GitHub"]
    assert row["detail"]["match"]["label"] == "Linus" and row["detail"]["top"]["label"] == "Namesake"


def test_detail_explains_the_level():
    case = {"id": "t", "expect": ["https://github.com/torvalds"]}
    linus = cand("Linus", "weak", ["https://github.com/torvalds"])
    linus.update(score=2.5, why=["same name"], contradictions=["age differs"], missing=["work"])
    row = ev.score_case(case, {"candidates": [linus]})
    assert row["detail"] == {"match": {"label": "Linus", "score": 2.5, "level": "weak", "why": ["same name"],
                                       "contradictions": ["age differs"], "missing": ["work"]}}
    assert "detail" not in ev.score_case(case, {"candidates": []})


def test_summary():
    rows = [{"rank": 1, "level": "strong", "false_strong": [], "wrongly_set_aside": [], "unchecked": []},
            {"rank": 3, "level": "weak", "false_strong": ["a", "b"], "wrongly_set_aside": [], "unchecked": ["GitHub"]},
            {"rank": None, "level": None, "false_strong": [], "wrongly_set_aside": ["x"], "unchecked": [],
             "error": "boom"}]
    totals = ev.summarize(rows)
    assert totals["hit@1"] == round(1 / 3, 3) and totals["hit@3"] == round(2 / 3, 3)
    assert totals["mrr"] == round((1 + 1 / 3) / 3, 3)
    assert totals["false_strong_per_case"] == round(2 / 3, 3)
    assert totals["wrongly_set_aside"] == 1 and totals["errors"] == 1 and totals["unchecked_cases"] == 1
    assert "| 3 |" not in ev.markdown([], ev.summarize([]))       # empty run does not divide by zero


def test_case_file_rules(tmp_path):
    bad = tmp_path / "c.jsonl"
    bad.write_text('{"id": "x", "text": "Ali"}\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        ev.load_cases(str(bad))


def test_public_cases_are_well_formed():
    cases = ev.load_cases(CASES)
    assert len(cases) >= 20
    for case in cases:
        assert case["kind"] == "public" and case["source"].startswith("https://www.wikidata.org/wiki/Q")
        assert all(u.startswith("https://github.com/") for u in case["expect"])


def test_wikidata_rows_become_cases():
    from datetime import date
    rows = [{"p": {"value": "http://www.wikidata.org/entity/Q34253"}, "pLabel": {"value": "Linus Torvalds"},
             "gh": {"value": "torvalds"}, "birth": {"value": "1969-12-28T00:00:00Z"},
             "res": {"value": "Helsinki|Santa Clara"}},
            {"p": {"value": "http://www.wikidata.org/entity/Q719413"}, "pLabel": {"value": "David Heinemeier Hansson"},
             "gh": {"value": "dhh"}, "birth": {"value": "1979-10-15T00:00:00Z"}, "res": {"value": "Malibu"}},
            {"p": {"value": "http://www.wikidata.org/entity/Q7637"}, "pLabel": {"value": "Q7637"},
             "gh": {"value": "x"}, "birth": {"value": "1949-01-01T00:00:00Z"}}]
    cases = wd.build(rows, date(2026, 11, 21))
    assert [c["text"] for c in cases] == ["David Heinemeier Hansson, 47 years old, from Malibu",
                                          "Linus Torvalds, 57 years old"]     # two towns: left out
    assert json.loads(json.dumps(cases))[1]["expect"] == ["https://github.com/torvalds"]


def test_a_candidate_built_on_the_handle_counts_when_github_did_not_answer():
    case = {"id": "t", "expect": ["https://github.com/Torvalds"]}
    built_on_handle = {"label": "@torvalds", "level": "strong", "fields": {}, "contacts": [],
                       "members": [{"type": "username", "query": "torvalds"}]}
    other = {"label": "@linus.t", "level": "strong", "fields": {}, "contacts": [],
             "members": [{"type": "username", "query": "linus.t"}]}
    row = ev.score_case(case, {"candidates": [other, built_on_handle]})
    assert row["rank"] == 2 and row["false_strong"] == ["@linus.t"]
    assert ev.expected_handles(["https://github.com/a/b", "https://example.com/x"]) == set()
