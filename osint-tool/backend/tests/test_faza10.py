"""Faza 10: same handle, different person (10.1) and score stability (10.2).

The data mirrors a real run: "torvalds" exists on GitHub (Linus, Portland),
Docker Hub (someone at an Italian company) and Bluesky (no name, a website
in the bio)."""
from datetime import date

import httpx
import pytest

from services import agent
from services.agent_parse import parse_request
from services.correlate import correlate
from services.deep_scan import unchecked_sources
from tools import public_profiles

TODAY = date(2026, 11, 21)
GITHUB = {"platform": "GitHub", "url": "https://github.com/torvalds", "status": "found",
          "info": "Name: Linus Torvalds; Company: Linux Foundation; Location: Portland, OR"}
DOCKER = {"platform": "Docker Hub", "url": "https://hub.docker.com/u/torvalds", "status": "found",
          "info": "Company: DoLoop srls; Location: Italy"}
BLUESKY = {"platform": "Bluesky", "url": "https://bsky.app/profile/torvalds.bsky.social", "status": "found",
           "info": "Bio: https://deadspace.wtf; Followers: 10"}
TELEGRAM = {"platform": "Telegram", "url": "https://t.me/torvalds", "status": "found", "info": "Name: ToRvaLDs"}


def _nodes(*items, via="knowledge_base"):
    return [
        {"key": "name:linus torvalds", "type": "name", "query": "Linus Torvalds", "depth": 0, "count": 1,
         "results": [{"platform": "Wikidata", "url": "https://www.wikidata.org/wiki/Q34253",
                      "info": "Name: Linus Torvalds; Born: 1969"}]},
        {"key": "username:torvalds", "type": "username", "query": "torvalds", "depth": 1, "via": via,
         "parent": "name:linus torvalds", "count": len(items), "results": [dict(i) for i in items]},
    ]


def _target(text="linus torvalds 56 years old from Portland"):
    return agent.Target(parse_request(text, TODAY))


# ---------------- 10.1 ----------------

def test_profile_of_another_person_is_set_aside():
    nodes = _nodes(GITHUB, DOCKER, BLUESKY, TELEGRAM)
    moved = _target().split_profiles(nodes)
    node = nodes[1]
    assert moved == 1
    assert [i["platform"] for i in node["results"]] == ["GitHub", "Bluesky", "Telegram"]
    assert node["set_aside"][0]["platform"] == "Docker Hub"
    assert "Italy" in node["set_aside"][0]["reason"]
    assert node["anchored"] == ["https://github.com/torvalds"]


def test_anchor_profile_gives_the_town_when_the_user_did_not():
    nodes = _nodes(GITHUB, DOCKER)
    _target("linus torvalds").split_profiles(nodes)
    assert [a["platform"] for a in nodes[1]["set_aside"]] == ["Docker Hub"]   # Italy vs Portland, OR


def test_other_name_or_birth_year_is_set_aside():
    other = {"platform": "GitLab", "url": "https://gitlab.com/torvalds", "status": "found",
             "info": "Name: Tom Valdez"}
    young = {"platform": "Chess.com", "url": "https://chess.com/member/torvalds", "status": "found",
             "info": "Name: Linus T; Born: 2004"}
    nodes = _nodes(GITHUB, other, young)
    _target().split_profiles(nodes)
    reasons = {a["platform"]: a["reason"] for a in nodes[1]["set_aside"]}
    assert "Tom Valdez" in reasons["GitLab"] and "2004" in reasons["Chess.com"]


def test_nothing_is_set_aside_without_anything_to_compare():
    nodes = _nodes(DOCKER, BLUESKY)
    assert agent.Target(parse_request("username torvalds", TODAY)).split_profiles(nodes) == 0
    assert "set_aside" not in nodes[1]


def test_candidate_has_no_contradiction_from_a_stranger_profile():
    target = _target()
    nodes = _nodes(GITHUB, DOCKER, BLUESKY)
    target.split_profiles(nodes)
    scan = {"nodes": nodes, "edges": [{"from": "name:linus torvalds", "to": "username:torvalds"}],
            "clusters": correlate(nodes)["clusters"]}
    candidates, _ = agent.rank(scan, target, set())
    top = candidates[0]
    assert top["label"] == "Linus Torvalds"
    assert not any("Italy" in c for c in top["contradictions"])
    assert "Italy" not in {v["value"] for v in top["fields"]["location"]}
    assert "DoLoop srls" not in {v["value"] for v in top["fields"]["work"]}
    assert top["set_aside"][0]["platform"] == "Docker Hub"
    # the website in the unconfirmed Bluesky bio is listed but marked, and not read
    site = next(c for c in top["contacts"] if c["kind"] == "website")
    assert site["confirmed"] is False and "not confirmed" in site["how"]


@pytest.mark.asyncio
async def test_only_confirmed_websites_are_read(monkeypatch):
    read = []

    async def fake_extract(url, max_pages=5):
        read.append(url)
        return {"contacts": [], "notes": []}

    monkeypatch.setattr(agent, "extract_contacts", fake_extract)
    candidates = [{"label": "Linus", "level": "strong", "contacts": [
        {"kind": "website", "value": "deadspace.wtf", "confirmed": False},
        {"kind": "website", "value": "torvalds.org", "confirmed": True}]}]
    assert await agent.read_candidate_sites(candidates) == 1
    assert read == ["torvalds.org"]


def test_contacts_from_a_stated_handle_are_confirmed():
    node = _nodes(BLUESKY, via="stated")[1]
    contacts = agent.profile_contacts([node])
    assert contacts and all(c["confirmed"] for c in contacts)


# ---------------- 10.2 ----------------

def test_unchecked_sources_are_read_from_warnings():
    result = {"warnings": ["GitHub: GitHub API rate limit reached. Set GITHUB_TOKEN to raise it.",
                           "45 site hit(s) ignored: those sites also report a random username",
                           "Hacker News: HTTP 400.", "GitLab: HTTP 503.", "Bluesky: ConnectError"],
              "failed_sources": ["Maigret"]}
    assert unchecked_sources(result) == ["Bluesky", "GitHub", "GitLab", "Maigret"]


def test_candidate_lists_sources_that_did_not_answer():
    target = _target()
    nodes = _nodes(DOCKER, BLUESKY)
    nodes[1]["unchecked"] = ["GitHub"]
    scan = {"nodes": nodes, "edges": [], "clusters": correlate(nodes)["clusters"]}
    candidates, _ = agent.rank(scan, target, set())
    assert any(c["unchecked"] == ["GitHub"] for c in candidates)


@pytest.mark.asyncio
async def test_github_answers_are_cached():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.path.endswith("/nobody"):
            return httpx.Response(404)
        return httpx.Response(200, json={"login": "torvalds", "name": "Linus Torvalds"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for _ in range(3):
            assert (await public_profiles.fetch_json(client, "https://api.github.com/users/torvalds"))["name"]
            assert await public_profiles.fetch_json(client, "https://api.github.com/users/nobody") is None
    assert len(calls) == 2                       # one real call each, then the cache


@pytest.mark.asyncio
async def test_github_rate_limit_is_not_cached():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for _ in range(2):
            with pytest.raises(Exception):
                await public_profiles.fetch_json(client, "https://api.github.com/users/torvalds")
    assert len(calls) == 2                       # a failure is retried next time, not remembered
