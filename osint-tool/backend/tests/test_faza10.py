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
    # two soft mismatches together (town AND workplace of the GitHub profile)
    assert "Italy" in node["set_aside"][0]["reason"] and "DoLoop" in node["set_aside"][0]["reason"]
    assert "info" not in node["set_aside"][0]                   # the stranger's bio is not kept
    assert node["anchored"] == ["https://github.com/torvalds"]


def test_anchor_values_alone_do_not_set_a_profile_aside():
    # town and workplace differ only from the GitHub profile, not from anything the
    # user said: maybe the same person before a move - kept (a score penalty only)
    nodes = _nodes(GITHUB, DOCKER)
    _target("linus torvalds").split_profiles(nodes)
    assert "set_aside" not in nodes[1]
    nodes = _nodes(GITHUB, DOCKER)
    _target("linus torvalds from Portland").split_profiles(nodes)   # the user's town + GitHub's workplace
    assert [a["platform"] for a in nodes[1]["set_aside"]] == ["Docker Hub"]


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
    assert unchecked_sources(result) == ["Bluesky", "GitHub", "GitLab", "Hacker News", "Maigret"]


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


# ---------------- QA regressions (10.1 / 10.2 review) ----------------

def _one(info, target_text, platform="Mastodon"):
    """Set-aside entries for the probed profile only (GitHub = Linus is there as context)."""
    nodes = _nodes(GITHUB, {"platform": platform, "url": f"https://{platform.lower()}.example/torvalds",
                            "status": "found", "info": info})
    _target(target_text).split_profiles(nodes)
    return [a for a in nodes[1].get("set_aside") or [] if a["platform"] == platform]


@pytest.mark.parametrize("info,target_text", [
    ("Location: USA", "linus torvalds 56 years old from Portland"),
    ("Location: Oregon", "linus torvalds 56 years old from Portland"),
    ("Location: remote", "linus torvalds 56 years old from Portland"),
    ("Location: Helsinki", "linus torvalds 56 years old from Portland"),          # people move
    ("Location: Uzbekistan", "Lutfullo Abdubaniyev 19 yosh Toshkentdan"),
    ("Location: Moscow, Russia", "Lutfullo Abdubaniyev 19 yosh Namangandan"),
    ("Company: Transmeta; Location: Santa Clara", "linus torvalds 56 years old"),  # alone: name decides
])
def test_one_soft_mismatch_never_sets_a_profile_aside(info, target_text):
    assert _one(info, target_text) == []


@pytest.mark.parametrize("name,target_text", [
    ("Якубжон Юлдашев", "Yoqubjon Yo'ldoshev 30 yosh"),
    ("Yakubjon Yuldashev", "Yoqubjon Yo'ldoshev 30 yosh"),
    ("Лутфулло Абдубаниев", "Lutfullo Abdubaniyev 19 yosh"),
    ("Sasha P.", "Aleksandr Petrov"),
    ("Linus Benedict Torvalds", "linus torvalds"),
])
def test_spelling_variants_and_nicknames_are_the_same_person(name, target_text):
    assert _one(f"Name: {name}", target_text) == []


def test_bio_labels_are_not_read_as_fields():
    assert _one("Bio: hacker; Company name: Linux Foundation; Previous location: Italy",
                "linus torvalds 56 years old from Portland") == []
    from services.correlate import _LOC_RE, _NAME_RE
    assert _NAME_RE.findall("Bio: x; Company name: Linux Foundation") == []
    assert _LOC_RE.findall("Previous location: Italy; Location: Portland") == ["Portland"]


def test_a_namesake_with_the_same_name_is_not_trusted():
    # same name, other age and town: not an anchor, and set aside by its birth year
    namesake = {"platform": "Docker Hub", "url": "https://hub.docker.com/u/torvalds", "status": "found",
                "info": "Name: Linus Torvalds; Location: Milan, Italy; Born: 1999"}
    nodes = _nodes(GITHUB, namesake)
    _target().split_profiles(nodes)
    assert [a["platform"] for a in nodes[1]["set_aside"]] == ["Docker Hub"]
    assert nodes[1]["anchored"] == ["https://github.com/torvalds"]


def test_a_common_name_anchor_does_not_push_out_real_profiles():
    github = {"platform": "GitHub", "url": "https://github.com/akarimov", "status": "found",
              "info": "Name: Aziz Karimov; Location: Moscow"}
    bluesky = {"platform": "Bluesky", "url": "https://bsky.app/profile/akarimov", "status": "found",
               "info": "Location: Tashkent"}
    nodes = _nodes(github, bluesky)
    agent.Target(parse_request("Aziz Karimov", TODAY)).split_profiles(nodes)
    assert "set_aside" not in nodes[1]


def test_pivots_of_a_set_aside_profile_are_dropped():
    docker = {**DOCKER, "info": "Company: DoLoop srls; Location: Italy; Website: doloop.it"}
    nodes = _nodes(GITHUB, docker)
    nodes[1]["pivots"] = [{"type": "domain", "value": "doloop.it", "via": "profile_link"},
                          {"type": "username", "value": "torvalds", "via": "profile_link"}]
    _target().split_profiles(nodes)
    assert [p["value"] for p in nodes[1]["pivots"]] == ["torvalds"]     # also in the kept GitHub URL
    assert nodes[1]["dropped_pivots"] == 1


@pytest.mark.asyncio
async def test_deep_scan_does_not_follow_a_set_aside_profile(monkeypatch):
    from services import deep_scan

    async def username(value):
        return {"status": "success", "results": [dict(GITHUB),
                                                 {**DOCKER, "info": DOCKER["info"] + "; Website: doloop.it"}],
                "count": 2, "pivots": [{"type": "domain", "value": "doloop.it", "via": "profile_link"}]}

    async def domain(value):
        return {"status": "success", "results": [{"platform": "WHOIS", "info": "Email: info@doloop.it"}],
                "count": 1, "pivots": []}

    monkeypatch.setitem(deep_scan._HANDLERS, "username", username)
    monkeypatch.setitem(deep_scan._HANDLERS, "domain", domain)
    target = _target("linus torvalds 56 years old from Portland, works at Linux Foundation")
    scan = await deep_scan.run_deep_scan("torvalds", "username", expand=target.expand,
                                         prepare=target.split_profiles)
    # the seed is via None (not "stated") here, so it is checked like a found handle
    assert {n["key"] for n in scan["nodes"]} == {"username:torvalds"}
    assert scan["nodes"][0]["set_aside"][0]["platform"] == "Docker Hub"


def test_contacts_from_an_email_found_on_a_profile_are_not_confirmed():
    email = {"key": "email:x@doloop.it", "type": "email", "query": "x@doloop.it", "via": "profile_link",
             "results": [{"platform": "Gravatar", "url": "https://gravatar.com/x", "status": "found",
                          "info": "Website: doloop.it"}]}
    assert all(not c["confirmed"] for c in agent.profile_contacts([email]))
    # a knowledge base names one account (GitHub), not every site with the handle
    listed = {**_nodes(BLUESKY)[1], "via": "knowledge_base"}
    assert all(not c["confirmed"] for c in agent.profile_contacts([listed]))


def test_odd_values_do_not_break_the_check():
    weird = {"platform": "X", "url": "https://x.example", "status": "found", "name": ["not", "text"],
             "info": None}
    nodes = _nodes(GITHUB, weird)
    nodes[1]["results"].append("just a string")
    _target().split_profiles(nodes)                                    # no exception


@pytest.mark.asyncio
async def test_github_cache_survives_neither_a_wipe_nor_an_incomplete_search(monkeypatch):
    from cache import _memory
    from services import data_wipe

    def handler(request):
        if "/search/" in request.url.path:
            return httpx.Response(200, json={"total_count": 0, "incomplete_results": True, "items": []})
        return httpx.Response(200, json={"login": "torvalds"})

    real_fetch = public_profiles._fetch_json

    async def fetch_then_wipe(*args, **kwargs):
        data = await real_fetch(*args, **kwargs)
        await data_wipe.wipe_everything()           # deletion lands while the request is in flight
        return data

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await public_profiles.fetch_json(client, "https://api.github.com/search/users", params={"q": "x"})
        assert not any(k.startswith("osint:github:") for k in _memory)
        monkeypatch.setattr(public_profiles, "_fetch_json", fetch_then_wipe)
        await public_profiles.fetch_json(client, "https://api.github.com/users/torvalds")
    assert not any(k.startswith("osint:github:") for k in _memory)


def test_github_cache_key_depends_on_missing_codes_and_encodes_params():
    k = public_profiles._github_cache_key
    url = "https://api.github.com/search/users"
    assert k(url, {"q": "a"}, (404,)) != k(url, {"q": "a"}, (404, 422))
    assert k(url, {"q": "a&b=c"}, (404,)) != k(url, {"q": "a", "b": "c"}, (404,))


def test_failure_labels_are_clean():
    result = {"warnings": ["Web search failed unexpectedly: ReadTimeout",
                           "Truecaller skipped: host unreachable",
                           "GitHub: HTTP 403.", "Bluesky: RemoteProtocolError",
                           "Keybase: malformed JSON.", "GitLab: HTTP 404.",
                           "45 site hit(s) ignored: those sites also report a random username"]}
    assert unchecked_sources(result) == ["Bluesky", "GitHub", "Keybase", "Truecaller", "Web search"]


# ---------------- 10.5: what the first evaluation found ----------------

@pytest.mark.parametrize("text,name,places", [
    ("Terence Tao, 51 years old, from United States", "Terence Tao", ["United States"]),
    ("Ian Goodfellow, 39 years old, from San Francisco", "Ian Goodfellow", ["San Francisco"]),
    ("ian goodfellow 39 years old from san francisco", "Ian Goodfellow", ["San Francisco"]),
    ("Tim Berners-Lee, 71 years old, from Concord", "Tim Berners-Lee", ["Concord"]),
    ("Ali Valiyev from Ann Arbor", "Ali Valiyev", ["Ann Arbor"]),
    ("from Namangan Ali Valiyev", "Ali Valiyev", ["Namangan"]),        # a known town first: rest is the name
    ("Linus Torvalds, 56 years old, from Portland", "Linus Torvalds", ["Portland"]),
    ("Иван Петров из Санкт-Петербурга", "Иван Петров", None),
])
def test_places_of_several_words_stay_out_of_the_name(text, name, places):
    parsed = parse_request(text, TODAY)
    assert parsed["names"] == [name]
    if places is not None:
        assert parsed["places"] == places


@pytest.mark.asyncio
async def test_gitlab_answers_are_cached_too():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=[{"web_url": "https://gitlab.com/ali", "name": "Ali"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for _ in range(3):
            assert (await public_profiles.gitlab_profile(client, "ali"))["url"] == "https://gitlab.com/ali"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_hacker_news_is_not_asked_for_impossible_ids():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await public_profiles.hackernews_profile(client, "linus.torvalds") is None
    assert calls == []                         # no request, so no "Hacker News: HTTP 400" warning


def test_domain_failures_do_not_mark_the_person_unchecked():
    target = _target()
    nodes = _nodes(GITHUB)
    nodes[1]["unchecked"] = ["GitLab"]
    nodes.append({"key": "host:torvalds.org", "type": "domain", "query": "torvalds.org", "depth": 2,
                  "via": "profile_link", "parent": "username:torvalds", "count": 1,
                  "results": [{"platform": "DNS", "info": "A 1.2.3.4"}], "unchecked": ["Subdomains", "Reverse IP"]})
    scan = {"nodes": nodes, "edges": [{"from": "username:torvalds", "to": "host:torvalds.org"}],
            "clusters": [{"members": ["name:linus torvalds", "username:torvalds", "host:torvalds.org"], "score": 5}]}
    candidates, _ = agent.rank(scan, target, set())
    assert candidates[0]["unchecked"] == ["GitLab"]
