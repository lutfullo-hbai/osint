"""Agent mode (Faza 6): parse, plan, pivot filter, ranking, live steps, decisions."""
import asyncio
import importlib
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from security import limiter
from services import agent, deep_scan
from services.agent_parse import describe, has_target, parse_request

TODAY = date(2026, 11, 19)


# ---------------- 6.1 parser ----------------

@pytest.mark.parametrize("text, name, age, years, places", [
    ("lutfullo abdubaniyev 19 yosh namangandan", "Lutfullo Abdubaniyev", 19, [2006, 2007], ["Namangan"]),
    ("Лутфулла Абдубаниев, 19 лет, из Намангана", "Лутфулла Абдубаниев", 19, [2006, 2007], ["Namangan"]),
    ("John Smith 34 years old from London", "John Smith", 34, [1991, 1992], ["London"]),
    ("aziz karimov toshkentlik 1998 yilda tug'ilgan", "Aziz Karimov", None, [1998], ["Tashkent"]),
    ("Farg'onadan Dilnoza 25 yoshda", "Dilnoza", 25, [2000, 2001], ["Fergana"]),
    ("Popov Ivan", "Popov Ivan", None, [], []),          # "pop" (a town) must not eat "Popov"
])
def test_parse_free_text(text, name, age, years, places):
    p = parse_request(text, TODAY)
    assert p["names"] == [name]
    assert p["age"] == age and p["birth_years"] == years and p["places"] == places


def test_parse_identifiers_and_never_invents():
    p = parse_request("@lutfullo_dev t.me/somebody example.uz Test@Mail.ru +998 90 123 45 67", TODAY)
    assert set(p["usernames"]) == {"lutfullo_dev", "somebody"}
    assert p["emails"] == ["test@mail.ru"] and p["domains"] == ["example.uz"]
    assert p["phones"] == ["+998901234567"] and p["names"] == []
    assert has_target(p) and "username" in describe(p)
    assert not has_target(parse_request("19 yosh namangandan", TODAY))


# ---------------- plan / pivot filter ----------------

def test_plan_adds_birth_year_handles_under_the_name():
    primary, extras = agent.plan(parse_request("lutfullo abdubaniyev 19 yosh", TODAY))
    assert primary == {"type": "name", "value": "Lutfullo Abdubaniyev", "via": "stated"}
    guesses = [e["value"] for e in extras if e["via"] == "name_variant"]
    assert guesses == ["lutfulloabdubaniyev07", "lutfulloabdubaniyev06"]
    assert all(e["parent"] == "name:lutfullo abdubaniyev" for e in extras)


def test_expand_skips_contradicting_namesake():
    target = agent.Target(parse_request("lutfullo abdubaniyev 19 yosh namangandan", TODAY))
    namesake = {"depth": 1, "via": "name_match", "type": "username", "query": "x",
                "results": [{"platform": "VK", "url": "https://vk.com/x", "info": "Born: 1980"}]}
    follow, reason = target.expand(namesake)
    assert not follow and "1980" in reason
    same = dict(namesake, results=[{"platform": "GH", "url": "https://github.com/x",
                                     "info": "Location: Namangan; Born: 2007"}])
    assert target.expand(same) == (True, "")
    assert target.expand(dict(namesake, depth=0)) == (True, "")      # seeds always run


# ---------------- end to end with fake investigators ----------------

def _handler(table):
    async def handler(value):
        results, pivots = table.get(value, ([], []))
        return {"status": "success", "query": value, "results": results,
                "count": len(results), "pivots": pivots}
    return handler


@pytest.fixture()
def fake_sources(monkeypatch):
    monkeypatch.setattr(deep_scan, "AI_REVIEW", False)
    names = {"Lutfullo Abdubaniyev": (
        [{"platform": "Web", "url": "https://news.example/a", "source": "web_search", "info": "mention"}],
        [{"type": "username", "value": "lutfullo_dev", "via": "name_match"},
         {"type": "username", "value": "labdubaniyev", "via": "name_match"}])}
    users = {
        "lutfullo_dev": ([{"platform": "GitHub", "url": "https://github.com/lutfullo_dev", "status": "found",
                           "info": "Name: Lutfullo Abdubaniyev; Location: Namangan, Uzbekistan; Born: 2007"}],
                         [{"type": "domain", "value": "lutfullo.uz", "via": "profile_link"}]),
        "labdubaniyev": ([{"platform": "VK", "url": "https://vk.com/labdubaniyev", "status": "found",
                           "info": "Name: Lutfullo Abdubaniyev; Location: Moscow; Born: 1980"}],
                         [{"type": "domain", "value": "other.ru", "via": "profile_link"}]),
    }
    domains = {"lutfullo.uz": ([{"platform": "WHOIS", "url": "https://lutfullo.uz", "status": "found",
                                 "info": "Registered 2024"}], [])}
    monkeypatch.setitem(deep_scan._HANDLERS, "name", _handler(names))
    monkeypatch.setitem(deep_scan._HANDLERS, "username", _handler(users))
    monkeypatch.setitem(deep_scan._HANDLERS, "domain", _handler(domains))


@pytest.mark.asyncio
async def test_run_agent_ranks_by_age_and_place(fake_sources):
    steps = []
    result = await agent.run_agent("lutfullo abdubaniyev 19 yosh namangandan",
                                   lambda kind, text: steps.append((kind, text)))
    kinds = [k for k, _ in steps]
    assert kinds[:2] == ["parse", "plan"] and kinds[-2:] == ["link", "rank"]
    assert any(k == "skip" and "labdubaniyev" in t and "1980" in t for k, t in steps)

    top, *rest = result["candidates"]
    assert top["level"] == "strong" and "lutfullo_dev" in [m["query"] for m in top["members"]]
    assert any("fits the age" in w for w in top["why"]) and any("Namangan" in w for w in top["why"])
    # every field value carries the page it came from
    location = top["fields"]["location"][0]
    assert location["value"].startswith("Namangan")
    assert location["sources"][0]["url"] == "https://github.com/lutfullo_dev"
    assert "emails" in top["missing"]

    namesake = next(c for c in rest if any(m["query"] == "labdubaniyev" for m in c["members"]))
    assert namesake["level"] == "weak" and namesake["score"] < top["score"]
    assert any("1980" in c for c in namesake["contradictions"])
    # the skipped namesake's own pivot was never scanned
    assert "host:other.ru" not in {n["key"] for n in result["scan"]["nodes"]}
    assert result["notice"].startswith("Candidates are leads")


@pytest.mark.asyncio
async def test_run_agent_rejects_text_without_target():
    from services.investigate import InvestigationValidationError
    with pytest.raises(InvestigationValidationError):
        await agent.run_agent("19 yosh namangandan")


# ---------------- API: live steps + human decision ----------------

@pytest.fixture()
def store_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CASES_DB_PATH", str(tmp_path / "cases.db"))
    import store
    importlib.reload(store)
    store.init_db()
    limiter.reset()
    yield store
    limiter.reset()


@pytest.mark.asyncio
async def test_agent_api_runs_logs_steps_and_records_decision(store_mod, fake_sources, monkeypatch):
    import main
    from routers import jobs

    monkeypatch.setattr(jobs, "REDIS_URL", "")
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        started = (await client.post("/api/agent", json={"text": "lutfullo abdubaniyev 19 yosh namangandan"})).json()
        assert started["status"] == "queued" and started["mode"] == "local"
        run_id = started["run_id"]
        for _ in range(100):
            run = (await client.get(f"/api/agent/{run_id}")).json()["run"]
            if run["status"] in ("complete", "failed"):
                break
            await asyncio.sleep(0.05)
        assert run["status"] == "complete", run.get("error")
        assert run["steps"][0]["kind"] == "parse"
        later = (await client.get(f"/api/agent/{run_id}?after=2")).json()["run"]
        assert later["steps"][0]["seq"] == 3

        cand = run["result"]["candidates"][0]["id"]
        ok = await client.post(f"/api/agent/{run_id}/decision", json={"candidate_id": cand, "decision": "confirmed"})
        bad = await client.post(f"/api/agent/{run_id}/decision", json={"candidate_id": "nope", "decision": "confirmed"})
        wrong = await client.post(f"/api/agent/{run_id}/decision", json={"candidate_id": cand, "decision": "maybe"})
        assert ok.status_code == 200 and bad.status_code == 400 and wrong.status_code == 400
        run = (await client.get(f"/api/agent/{run_id}")).json()["run"]
        assert run["decisions"][cand]["decision"] == "confirmed"
        undo = await client.post(f"/api/agent/{run_id}/decision", json={"candidate_id": cand, "decision": "undecided"})
        assert undo.status_code == 200
        assert (await client.get(f"/api/agent/{run_id}")).json()["run"]["decisions"] == {}

        assert (await client.get("/api/agent")).json()["runs"][0]["id"] == run_id
        assert (await client.get("/api/agent/missing")).status_code == 404
        assert (await client.post("/api/agent", json={"text": "   "})).status_code == 400


def test_name_alone_is_not_a_candidate_and_empty_guesses_are_dropped():
    target = agent.Target(parse_request("lutfullo abdubaniyev 19 yosh", TODAY))
    scan = {"nodes": [
        {"key": "name:lutfullo abdubaniyev", "type": "name", "query": "Lutfullo Abdubaniyev", "count": 1,
         "results": [{"platform": "UZ register", "url": "https://data.egov.uz/x", "info": "Director"}]},
        {"key": "username:lutfulloabdubaniyev07", "type": "username", "query": "lutfulloabdubaniyev07",
         "count": 0, "results": [], "via": "name_variant"},
    ], "clusters": [
        {"members": ["name:lutfullo abdubaniyev"], "score": 0},
        {"members": ["username:lutfulloabdubaniyev07"], "score": 0},
    ]}
    candidates, overview = agent.rank(scan, target, {"name:lutfullo abdubaniyev"})
    assert candidates == []
    assert overview["name_search"][0]["url"] == "https://data.egov.uz/x"


@pytest.mark.asyncio
async def test_username_canary_filters_catch_all_sites(monkeypatch):
    from tools import username_canary

    async def sherlock(handle):
        return {"results": [{"platform": "7Cups"}, {"platform": "Airliners"}]}

    async def maigret(handle):
        raise RuntimeError("down")
    import tools.maigret_runner as mr
    import tools.sherlock_runner as sr
    monkeypatch.setattr(sr, "run_sherlock", sherlock)
    monkeypatch.setattr(mr, "run_maigret", maigret)
    saved = {}

    async def fake_load():
        return saved.get("v") or {"tools": {"maigret": ["oldsite"]}}

    async def fake_set(key, value, ttl):
        saved["v"] = value
    monkeypatch.setattr(username_canary, "load", fake_load)
    monkeypatch.setattr(username_canary, "set_cached_json", fake_set)
    report = await username_canary.run_canary()
    assert report["sherlock"] == 2 and report["maigret"].startswith("failed")
    sites = await username_canary.false_positive_sites()
    assert sites["sherlock"] == {"7cups", "airliners"} and sites["maigret"] == {"oldsite"}  # last good list kept
    kept, dropped = username_canary.drop_false_positives(
        [{"platform": "7Cups"}, {"platform": "GitHub"}], sites["sherlock"])
    assert kept == [{"platform": "GitHub"}] and dropped == 1


def test_catch_all_site_found_for_every_guess_is_ignored():
    def node(handle, platforms):
        return {"key": f"username:{handle}", "type": "username", "query": handle, "count": len(platforms),
                "via": "name_variant",
                "results": [{"platform": p, "url": f"https://{p.lower()}.example/{handle}", "status": "found"}
                            for p in platforms]}
    nodes = [node("a07", ["Hubski"]), node("a06", ["Hubski"]), node("a", ["Hubski", "YouTube"]),
             node("a.b", ["Hubski", "Codepen"])]
    scan = {"nodes": nodes, "clusters": [{"members": [n["key"]], "score": 0} for n in nodes]}
    target = agent.Target(parse_request("a b", TODAY))
    candidates, overview = agent.rank(scan, target, set())
    assert overview["ignored_platforms"] == ["hubski"]
    # only the handles with a credible profile left remain
    assert sorted(c["members"][0]["query"] for c in candidates) == ["a", "a.b"]
    assert all("Hubski" not in [p["value"] for p in c["fields"]["profiles"]] for c in candidates)


def test_placeholder_values_are_not_fields():
    node = {"key": "username:x", "type": "username", "query": "x", "results": [
        {"platform": "GitHub", "url": "https://github.com/x", "status": "found",
         "info": "Name: Linus Torvalds; Company: Company; Location: Location"}]}
    fields = agent.profile_fields([node])
    assert fields["location"] == [] and fields["name"][0]["value"] == "Linus Torvalds"


def test_agreement_message_names_the_matching_value():
    target = agent.Target(parse_request("linus torvalds 56 years old from Portland", TODAY))
    assert target.place_check({"Italy", "Portland, OR"}) == (agent.B_PLACE_AGREE, "location 'Portland, OR' matches Portland")
    assert target.age_check({1950, 1970})[1].startswith("birth year 1970")
