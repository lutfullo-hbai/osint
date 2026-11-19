"""Faza 7: person card, published contacts, document dorks, orginfo.uz,
manual-check links, narrowing fields, contact extractor, graph export."""
import csv
import importlib
import io
import json
import xml.etree.ElementTree as ET
from datetime import date

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from security import limiter
from services import agent, graph_export, person_card
from services.agent_parse import describe, parse_request
from tools import contact_extract, name_search, orginfo

TODAY = date(2026, 11, 19)


# ---------------- 7.4 orginfo.uz ----------------

def _card(org_id, stir, date_, org, person):
    return f'''
<a href="/uz/organization/{org_id}/" class="text-decoration-none og-card" role="button">
  <div class="card"><div class="d-flex"><p>
    <span class="bg-success bg-opacity-25 text-success px-2 py-1 rounded-5">{stir}</span></p>
    <p><span class="text-body-tertiary"><img src="/static/assets/img/calendar.svg" alt="calendar">
      {date_}</span></p></div>
  <div class="card-body pt-0"><h6 class="card-title">{org}</h6>
    <p class="text-body-tertiary mb-0">
      <img width="18" height="18" src="/static/assets/img/tab_managers.svg" alt="location">
      {person}
    </p></div></div></a>'''


ORG_PAGE = '''<html><head><script type="application/ld+json">[{"@context": "https://schema.org",
"@type": "WebPage", "dateModified": "2024-06-25T13:12:36+00:00", "mainEntity": {"@type": "Organization",
"name": "\\"ARTEL ELECTRONICS\\" mas`uliyati cheklangan jamiyati", "alternateName": "\\"ARTEL ELECTRONICS\\" MCHJ",
"taxID": "307221939", "url": "https://artelgroup.org", "email": "info@example.uz", "telephone": "781488888",
"address": {"@type": "PostalAddress", "addressLocality": "Toshkent shahri", "streetAddress": "Maxtumquli 2"},
"foundingDate": "2020-03-11", "employee": {"@type": "Person", "name": "RO`ZIQULOV SHOHRUH TOHIROVICH",
"jobTitle": "Rahbar"}, "founder": [{"@type": "Person", "name": "ARTIKXODJAYEV JAXONGIR ABIDOVICH"},
{"@type": "Organization", "name": "SOME HOLDING"}, {"@type": "Person", "name": "ARTEL ELECTRONICS MCHJ"}]}}]</script></head></html>'''


def test_orginfo_parses_cards_and_organisation_page():
    page = _card("2341d46afea9", "307221939", "11.03.2020", "&quot;ARTEL&quot; MCHJ", "RO`ZIQULOV SHOHRUH")
    cards = orginfo.parse_cards(page)
    assert cards == [{"id": "2341d46afea9", "stir": "307221939", "registered": "11.03.2020",
                      "name": '"ARTEL" MCHJ', "person": "RO`ZIQULOV SHOHRUH"}]
    entity = orginfo.parse_organization(ORG_PAGE)
    assert entity["taxID"] == "307221939" and entity["as_of"] == "2024-06-25"
    result, pivots = orginfo.org_result("2341d46afea9", entity)
    assert result["reliability"] == "medium" and "Reliability: medium" in result["info"]
    assert "Head: RO`ZIQULOV SHOHRUH TOHIROVICH" in result["info"]
    assert "Founders: ARTIKXODJAYEV JAXONGIR ABIDOVICH" in result["info"]   # the company founder is not a person
    assert {"type": "domain", "value": "artelgroup.org", "via": "official_register"} in pivots
    assert {p["value"] for p in pivots if p["type"] == "name"} == {
        "Ro`ziqulov Shohruh Tohirovich", "Artikxodjayev Jaxongir Abidovich"}   # the MCHJ "person" is a company


def test_register_spelling_uses_backtick():
    assert orginfo.register_spelling("Ro'ziqulov  Shohruh") == "RO`ZIQULOV SHOHRUH"


@pytest.mark.asyncio
async def test_orginfo_person_search_keeps_only_real_name_matches(monkeypatch):
    pages = {
        "managers": _card("aaa111bbb222", "305252861", "27.01.2018", "ARTEL MANUFACTURING", "GULYAMOV XURSHID SUNNATULLAYEVICH")
                    + _card("ccc333ddd444", "305844038", "07.11.2018", "ALLMEDIA", "GULYAMOV BAXTIYOR RUSTAMOVICH"),
        "founders": _card("eee555fff666", "301111111", "01.01.2015", "XYZ", "XURSHID GULYAMOV O`G`LI"),
    }
    asked = []

    async def fake_page(path):
        asked.append(path)
        return pages["managers" if "/managers/" in path else "founders"]

    monkeypatch.setattr(orginfo, "_get_page", fake_page)
    out = await orginfo.lookup_person("Xurshid G'ulyamov")
    assert all("q=XURSHID%20G%60ULYAMOV" in p for p in asked)
    infos = [r["info"] for r in out["results"]]
    assert len(infos) == 2                               # BAXTIYOR is a different person
    assert "head (rahbar)" in infos[0] and "founder (ta'sischi)" in infos[1]
    assert {p["value"] for p in out["pivots"]} == {"305252861", "301111111"}
    assert all(p["type"] == "company" for p in out["pivots"])


@pytest.mark.asyncio
async def test_orginfo_company_lookup_reads_detail_pages(monkeypatch):
    async def fake_page(path):
        if path.startswith("/uz/search/organizations/"):
            return _card("2341d46afea9", "307221939", "11.03.2020", "ARTEL", "RO`ZIQULOV SHOHRUH")
        return ORG_PAGE

    monkeypatch.setattr(orginfo, "_get_page", fake_page)
    out = await orginfo.lookup_company("artel")
    assert out["results"][0]["url"] == "https://orginfo.uz/uz/organization/2341d46afea9/"
    assert any(p["type"] == "name" for p in out["pivots"])


@pytest.mark.asyncio
async def test_name_investigation_includes_orginfo_and_manual_links(monkeypatch):
    from services import investigate as inv

    async def empty(*args, **kwargs):
        return {"results": [], "pivots": [], "warnings": [], "dropped": 0}

    async def entity(name):
        return {"results": [], "pivots": []}

    async def people(name):
        return {"results": [{"platform": "orginfo.uz — company head", "url": "https://orginfo.uz/uz/organization/x/",
                             "status": "found", "info": "Person: X"}],
                "pivots": [{"type": "company", "value": "305252861", "via": "official_register"}]}

    monkeypatch.setattr(inv, "run_name_search", empty)
    monkeypatch.setattr(inv, "run_name_sources", empty)
    monkeypatch.setattr(inv, "run_person_entity", entity)
    monkeypatch.setattr(inv, "run_sanctions_check", empty)
    monkeypatch.setattr(inv.uz_registry, "search_person", lambda name: [])
    monkeypatch.setattr(inv.orginfo, "lookup_person", people)
    out = await inv._investigate_name("Xurshid Gulyamov")
    assert out["results"][0]["platform"].startswith("orginfo.uz")
    assert {"type": "company", "value": "305252861", "via": "official_register"} in out["pivots"]
    labels = " ".join(link["label"] for link in out["links"])
    assert "public.sud.uz" in labels and "data.egov.uz" in labels and "orginfo.uz" in labels
    assert all(link["checked"] is False for link in out["links"])


# ---------------- 7.3 documents, 7.5 manual links ----------------

def test_name_search_asks_for_documents_and_labels_them():
    batches = name_search.build_batches(["Aziz Karimov"])
    assert any("filetype:pdf" in b and "filetype:xlsx" in b for b in batches)
    items = name_search.mark_documents([
        {"platform": "lex.uz", "url": "https://lex.uz/files/list.PDF?x=1", "title": "Aziz Karimov"},
        {"platform": "kun.uz", "url": "https://kun.uz/news/1", "title": "Aziz Karimov"},
    ])
    assert items[0]["kind"] == "document" and items[0]["platform"] == "Document (PDF) — lex.uz"
    assert "kind" not in items[1]


def test_manual_links_are_built_from_the_name_only():
    links = name_search.name_manual_links("Ro'ziqulov Shohruh")
    by_label = {link["label"]: link["url"] for link in links}
    assert by_label["orginfo.uz — company heads"].endswith("?q=RO%60ZIQULOV+SHOHRUH")
    assert any(url == "https://public.sud.uz/" for url in by_label.values())


# ---------------- 7.6 narrowing fields ----------------

@pytest.mark.parametrize("text, name, places, work, school", [
    ("Aziz Karimov Artelda ishlaydi, Toshkentdan", "Aziz Karimov", ["Tashkent"], ["Artel"], []),
    ("Aziz Karimov Artel kompaniyasida ishlaydi 30 yosh", "Aziz Karimov", [], ["Artel kompaniyasi"], []),
    ("Dilnoza Rahimova Westminster universiteti talabasi samarqanddan", "Dilnoza Rahimova", ["Samarkand"], [],
     ["Westminster universiteti"]),
    ("Akmal Tursunov TATUda o'qiydi", "Akmal Tursunov", [], [], ["TATU"]),
    ("John Smith works at Google from London 35 years old", "John Smith", ["London"], ["Google"], []),
    ("John Smith, studied at MIT", "John Smith", [], [], ["MIT"]),
    ("Иван Петров работает в Яндексе, 30 лет", "Иван Петров", [], ["Яндексе"], []),
    ("Иван Петров работает в Ташкенте", "Иван Петров", ["Tashkent"], [], []),   # a town, not an employer
])
def test_parse_workplace_and_school(text, name, places, work, school):
    p = parse_request(text, TODAY)
    assert p["names"] == [name] and p["places"] == places
    assert p["workplaces"] == work and p["schools"] == school


def test_describe_mentions_workplace():
    assert "works at Google" in describe(parse_request("John Smith works at Google", TODAY))


def test_work_field_ignores_counts():
    members = [{"key": "username:a", "type": "username", "query": "a", "results": [
        {"platform": "GitLab", "url": "https://gitlab.com/a", "status": "found",
         "info": "Organizations: 10; Works: 3; Company: Linux Foundation"}]}]
    assert [v["value"] for v in agent.profile_fields(members)["work"]] == ["Linux Foundation"]


def test_org_check_rewards_matching_workplace_only():
    target = agent.Target(parse_request("Ivan Petrov works at Yandex", TODAY))
    bits, message = target.org_check({"Яндекс"})
    assert bits == agent.B_ORG_AGREE and "Yandex" in message
    assert target.org_check({"Google LLC"}) is None           # people change jobs: no penalty
    assert agent.Target(parse_request("Ivan Petrov", TODAY)).org_check({"Yandex"}) is None


# ---------------- 7.2 / 7.7 contact extractor ----------------

def test_phones_are_validated_not_just_digit_runs():
    text = "Tel: +998 90 123 45 67, ofis 71 202 33 44. ID 2024-11-19, narx 1 500 000 so'm, followers 901234"
    assert contact_extract.phones_in(text) == {"+998901234567", "+998712023344"}


def test_contacts_from_text_reads_email_phone_and_links():
    found = contact_extract.contacts_from_text(
        "Contact: ali [at] example [dot] uz | +998 93 555 11 22 | https://t.me/ali_dev "
        "https://github.com/alidev https://ali.uz/blog https://youtube.com/watch?v=1",
        "https://t.me/s/channel")
    pairs = {(c["kind"], c["value"]) for c in found}
    assert ("email", "ali@example.uz") in pairs and ("phone", "+998935551122") in pairs
    assert ("messenger", "https://t.me/ali_dev") in pairs
    assert ("social", "github.com/alidev") in pairs and ("website", "ali.uz") in pairs
    assert not any("youtube" in v for _, v in pairs)                       # a video is not a contact
    assert all(c["sources"] == ["https://t.me/s/channel"] for c in found)


def test_contacts_from_html_prefers_contact_pages():
    html = '''<a href="/blog/post-1">Post</a><a href="/kontakt">Kontakt</a>
      <a href="mailto:me@site.uz?subject=hi">mail</a><a href="tel:+998901112233">call</a>
      <a href="https://www.instagram.com/site_uz/">ig</a><script>var x="evil@tracker.com"</script>
      See https://lore.kernel.org/r/20191218090054.GA5120@kroah.com and 355aee5f-13ce-4e20-9ce8-e5bcddd14bc2@lf.org'''
    found, links = contact_extract.contacts_from_html(html, "https://site.uz/")
    pairs = {(c["kind"], c["value"]) for c in found}
    assert {("email", "me@site.uz"), ("phone", "+998901112233"), ("social", "instagram.com/site_uz")} <= pairs
    assert ("email", "evil@tracker.com") not in pairs                    # script content is not the page
    assert not any("kroah" in v or "355aee5f" in v for _, v in pairs)   # message ids, not addresses
    assert links == ["https://site.uz/kontakt", "https://site.uz/blog/post-1"]


@pytest.mark.asyncio
async def test_extract_contacts_obeys_robots_and_depth(monkeypatch):
    pages = {
        "https://site.uz/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /private"),
        "https://site.uz/": (200, "text/html", '<a href="/contact">c</a><a href="/private/x">p</a>'),
        "https://site.uz/contact": (200, "text/html", 'Email: info@site.uz <a href="/deeper">d</a>'),
        "https://site.uz/deeper": (200, "text/html", "deep@site.uz"),
    }
    fetched = []

    async def fake_get(client, url, **kwargs):
        fetched.append(url)
        status, ctype, body = pages.get(url, (404, "text/html", ""))
        return httpx.Response(status, headers={"content-type": ctype}, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(contact_extract, "safe_get", fake_get)
    monkeypatch.setattr(contact_extract, "PAUSE_SECONDS", 0)
    out = await contact_extract.extract_contacts("site.uz")
    assert out["pages"] == ["https://site.uz/", "https://site.uz/contact"]
    assert [c["value"] for c in out["contacts"]] == ["info@site.uz"]
    assert out["contacts"][0]["sources"] == ["https://site.uz/contact"]
    assert "https://site.uz/private/x" not in fetched and "https://site.uz/deeper" not in fetched
    assert any("robots.txt disallows /private/x" in n for n in out["notes"])


@pytest.mark.asyncio
async def test_extract_contacts_stops_when_robots_unavailable(monkeypatch):
    async def fake_get(client, url, **kwargs):
        return httpx.Response(503, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(contact_extract, "safe_get", fake_get)
    out = await contact_extract.extract_contacts("https://down.uz/")
    assert out["pages"] == [] and "not reading" in out["notes"][0]


def test_profile_contacts_read_only_self_written_text():
    members = [{"key": "username:ali", "type": "username", "query": "ali", "results": [
        {"platform": "GitHub", "url": "https://github.com/ali", "status": "found",
         "info": "Name: Ali; Followers: 901234567; Bio: write me +998 90 765 43 21; Website: ali.uz",
         "website": "ali.uz"},
        {"platform": "Web", "url": "https://x.example", "source": "web_search", "info": "Bio: spam@x.com"},
    ]}]
    contacts = agent.profile_contacts(members)
    pairs = {(c["kind"], c["value"]) for c in contacts}
    assert pairs == {("phone", "+998907654321"), ("website", "ali.uz")}
    assert contacts[0]["sources"] == ["https://github.com/ali"]
    assert contacts[0]["how"] == "written in the GitHub profile"


@pytest.mark.asyncio
async def test_top_candidate_websites_are_read(monkeypatch):
    calls = []

    async def fake_extract(site, max_pages):
        calls.append((site, max_pages))
        return {"contacts": [{"kind": "email", "value": "me@ali.uz", "sources": ["https://ali.uz/contact"],
                              "how": "written on the page"}], "notes": []}

    monkeypatch.setattr(agent, "extract_contacts", fake_extract)
    candidates = [
        {"label": "Ali", "level": "strong", "contacts": [{"kind": "website", "value": "ali.uz", "sources": []}]},
        {"label": "Weak", "level": "weak", "contacts": [{"kind": "website", "value": "weak.uz", "sources": []}]},
    ]
    steps = []

    async def say(kind, text):
        steps.append(text)

    assert await agent.read_candidate_sites(candidates, say) == 1
    assert calls == [("ali.uz", agent.SITE_PAGES)]
    assert {"kind": "email", "value": "me@ali.uz", "how": "published on ali.uz",
            "sources": ["https://ali.uz/contact"]} in candidates[0]["contacts"]
    assert steps == ["Reading contacts on ali.uz (linked by Ali)"]


# ---------------- 7.1 person card ----------------

SCAN = {
    "query": "Ali Valiyev", "seed_type": "name",
    "nodes": [
        {"key": "name:ali valiyev", "type": "name", "query": "Ali Valiyev", "depth": 0, "count": 1,
         "results": [{"platform": "Web", "url": "https://news.uz/a", "info": "=cmd|' /C calc'!A0"}]},
        {"key": "username:alidev", "type": "username", "query": "alidev", "depth": 1, "via": "name_match",
         "count": 1, "results": [{"platform": "GitHub", "url": "https://github.com/alidev", "info": "Name: Ali"}]},
        {"key": "phone:+998901234567", "type": "phone", "query": "+998901234567", "depth": 2,
         "via": "profile_link", "count": 0, "results": []},
    ],
    "edges": [{"from": "name:ali valiyev", "to": "username:alidev"},
              {"from": "username:alidev", "to": "phone:+998901234567"}],
    "clusters": [{"members": ["username:alidev", "phone:+998901234567"]}],
}


def test_evidence_chain_walks_back_to_the_search():
    chain = agent.evidence_chain(["phone:+998901234567"], SCAN)
    path = chain[0]["path"]
    assert [p["value"] for p in path] == ["Ali Valiyev", "alidev", "+998901234567"]
    assert path[0]["via"] == "you searched" and path[2]["via"] == "linked from a profile"


def _run():
    candidate = {"id": "abc123", "label": "Ali Valiyev", "level": "strong", "score": 8.5,
                 "fields": {"name": [{"value": "Ali Valiyev", "sources": [{"platform": "GitHub",
                                                                            "url": "https://github.com/alidev"}]}],
                            "profiles": [{"value": "GitHub", "sources": [{"platform": "GitHub",
                                                                           "url": "https://github.com/alidev"}]}]},
                 "missing": ["birth_year"], "why": ["same display name"], "contradictions": [],
                 "contacts": [{"kind": "phone", "value": "+998901234567", "how": "written in the GitHub profile",
                               "sources": ["https://github.com/alidev"]}],
                 "chain": agent.evidence_chain(["username:alidev"], SCAN), "members": []}
    return {"id": "run1", "text": "ali valiyev", "parsed": {},
            "result": {"query": "ali valiyev", "candidates": [candidate], "scan": SCAN},
            "decisions": {"abc123": {"decision": "confirmed", "note": "checked by phone"}}}


def test_person_card_carries_decision_and_renders_pdf():
    card = person_card.build_card(_run(), "abc123")
    assert card["decision"] == "confirmed" and card["decision_note"] == "checked by phone"
    assert card["candidate"]["contacts"][0]["value"] == "+998901234567"
    pdf = person_card.card_pdf(card)
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000
    with pytest.raises(person_card.CardError):
        person_card.build_card(_run(), "missing")


# ---------------- 7.8 graph export ----------------

def test_graphml_is_valid_and_carries_evidence():
    root = ET.fromstring(graph_export.to_graphml(SCAN))
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
    nodes = root.findall(".//g:node", ns)
    ids = {n.get("id") for n in nodes}
    assert {"name:ali valiyev", "username:alidev", "phone:+998901234567"} <= ids
    assert any(n.get("id").startswith("url:") for n in nodes)          # evidence pages are nodes too
    labels = [d.text for d in root.findall(".//g:edge/g:data", ns)]
    assert "same display name" in labels and "linked from a profile" in labels and "GitHub" in labels


def test_maltego_csv_rows_and_formula_escaping():
    rows = list(csv.reader(io.StringIO(graph_export.to_maltego_csv(SCAN))))
    assert rows[0] == graph_export.MALTEGO_COLUMNS
    assert ["maltego.Person", "Ali Valiyev", "maltego.Alias", "alidev", "same display name",
            "https://news.uz/a"] in rows
    assert ["maltego.Alias", "alidev", "maltego.PhoneNumber", "+998901234567", "linked from a profile",
            "https://github.com/alidev"] in rows                         # a phone keeps its "+"
    assert graph_export._cell("=cmd|' /C calc'!A0").startswith("'=")
    assert graph_export._cell("+998 90 123 45 67") == "+998 90 123 45 67"
    assert graph_export._cell("-2+3") == "'-2+3"


# ---------------- API ----------------

@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CASES_DB_PATH", str(tmp_path / "cases.db"))
    import store
    importlib.reload(store)
    store.init_db()
    limiter.reset()
    import main
    yield main, store
    limiter.reset()


@pytest.mark.asyncio
async def test_export_and_card_endpoints(api):
    main, store = api
    run = store.create_agent_run("ali valiyev")
    data = _run()
    store.update_agent_run(run["id"], status="complete", parsed={}, result=data["result"])
    store.set_agent_decision(run["id"], "abc123", "confirmed", "")
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        card = await client.get(f"/api/agent/{run['id']}/card/abc123")
        assert card.status_code == 200 and card.json()["card"]["decision"] == "confirmed"
        pdf = await client.get(f"/api/agent/{run['id']}/card/abc123/pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        assert "person-card-Ali_Valiyev.pdf" in pdf.headers["content-disposition"]
        assert (await client.get(f"/api/agent/{run['id']}/card/nope")).status_code == 404
        assert (await client.get("/api/agent/missing/card/abc123/pdf")).status_code == 404

        graphml = await client.get(f"/api/agent/{run['id']}/graph?format=graphml")
        assert graphml.status_code == 200 and graphml.text.startswith("<?xml")
        maltego = await client.get(f"/api/agent/{run['id']}/graph?format=maltego")
        assert maltego.status_code == 200 and maltego.text.startswith("source_entity_type")
        assert (await client.get(f"/api/agent/{run['id']}/graph?format=svg")).status_code == 400

        posted = await client.post("/api/export/graph", json={"scan": SCAN, "format": "graphml"})
        assert posted.status_code == 200 and 'filename="deep-scan-Ali_Valiyev.graphml"' in posted.headers[
            "content-disposition"]


@pytest.mark.asyncio
async def test_contacts_endpoint_rejects_private_addresses(api, monkeypatch):
    main, _ = api
    from routers import export

    async def fake_extract(url):
        return {"url": url, "contacts": [{"kind": "email", "value": "a@b.uz", "how": "x", "sources": [url]}],
                "pages": [url], "notes": []}

    async def safe(url):
        return url

    monkeypatch.setattr(export, "extract_contacts", fake_extract)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        bad = await client.post("/api/contacts", json={"url": "http://127.0.0.1/admin"})
        assert bad.status_code == 400
        monkeypatch.setattr(export, "ensure_safe_url", safe)
        ok = await client.post("/api/contacts", json={"url": "site.uz"})
        body = ok.json()
        assert ok.status_code == 200 and body["url"] == "https://site.uz" and body["contacts"][0]["value"] == "a@b.uz"
        assert "robots.txt" in body["notice"]


def test_json_import_unused_guard():
    # keeps the json import meaningful: card payloads are JSON-serialisable
    assert json.loads(json.dumps(person_card.build_card(_run(), "abc123")))["run_id"] == "run1"
