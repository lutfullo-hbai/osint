"""Faza 7 edge cases: malformed graph exports, odd person cards, contact-extractor
HTML quirks and robots.txt 401/403, SSRF variants, orginfo parsers on junk."""
import csv
import io
import xml.etree.ElementTree as ET

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from security import limiter
from services import graph_export, person_card
from tools import contact_extract, orginfo


# ---------- graph export with hostile / malformed scans ----------

HOSTILE = {
    "query": "a\x00b<script>\"&'",
    "nodes": [
        {"key": "name:x", "type": "name", "query": "=HYPERLINK(\"http://evil\")", "depth": 0,
         "results": [{"platform": "P\x07", "url": "https://e.uz/a?x=1&y=<2>", "info": "i\x01nfo"}]},
        {"key": "email:y", "type": "email", "query": "@SUM(1)", "depth": "1", "via": "profile_link",
         "results": [{"url": "javascript:alert(1)"}, {"url": None}]},
        {"key": "phone:z", "type": "phone", "query": "+998 90 123-45-67", "depth": None, "count": "3"},
        {"key": "u:w", "type": "weird", "query": "-2+3", "results": None},
    ],
    "edges": [{"from": "name:x", "to": "email:y"}, {"from": "name:x", "to": "ghost"}, {}],
    "clusters": [{"members": ["name:x", "email:y"]}, {"members": None}],
}


@pytest.mark.parametrize("scan", [
    HOSTILE,
    {},
    {"nodes": None, "edges": None},
    {"nodes": [{"type": "name", "query": "no key", "results": [{"url": "https://a.uz"}]}]},
    {"nodes": ["junk", 3, None], "edges": ["x"]},
])
def test_graphml_never_crashes_and_is_valid_xml(scan):
    ET.fromstring(graph_export.to_graphml(scan).encode())


@pytest.mark.parametrize("scan", [
    HOSTILE,
    {},
    {"nodes": [{"type": "name", "query": "no key", "results": [{"url": "https://a.uz"}]}]},
    {"nodes": ["junk", 3, None], "edges": ["x"]},
])
def test_maltego_never_crashes(scan):
    rows = list(csv.reader(io.StringIO(graph_export.to_maltego_csv(scan))))
    for row in rows[1:]:
        for cell in row:
            assert cell[:1] not in ("=", "@", "\t"), cell


def test_cell_cases():
    c = graph_export._cell
    assert c("+998 90 123-45-67") == "+998 90 123-45-67"
    assert c("=1+1").startswith("'")
    assert c("@x").startswith("'")
    assert c("-2+3").startswith("'")
    assert c("+cmd|' /C calc'!A0").startswith("'")
    assert c("\r=1") != "=1"


@pytest.mark.asyncio
async def test_export_endpoint_rejects_junk(tmp_path, monkeypatch):
    monkeypatch.setenv("CASES_DB_PATH", str(tmp_path / "c.db"))
    import importlib
    import store
    importlib.reload(store)
    store.init_db()
    limiter.reset()
    import main
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        for body in ({"scan": {"nodes": ["junk"]}, "format": "maltego"},
                     {"scan": {"nodes": [{"type": "x"}]}, "format": "maltego"},
                     {"scan": {"nodes": "abc"}, "format": "graphml"},
                     {"scan": {"query": 5, "nodes": []}, "format": "graphml"}):
            r = await client.post("/api/export/graph", json=body)
            assert r.status_code in (200, 400), (body, r.status_code, r.text[:200])
        r = await client.post("/api/export/graph",
                              json={"scan": {"nodes": [{"key": str(i)} for i in range(501)]}, "format": "graphml"})
        assert r.status_code == 400
        for url in ("localhost:8000/x", "[::1]/x", "http://0x7f000001/", "http://2130706433/",
                    "http://[::ffff:127.0.0.1]/", "http://metadata.google.internal/"):
            limiter.reset()
            r = await client.post("/api/contacts", json={"url": url})
            assert r.status_code == 400, (url, r.text)
    limiter.reset()


# ---------- person card with odd candidates ----------

def test_card_pdf_with_odd_values():
    long_url = "https://example.uz/" + "a" * 400
    run = {"id": "r", "text": "q", "decisions": {"c1": {"decision": "rejected", "note": "x" * 2000}},
           "result": {"candidates": [{
               "id": "c1", "label": None, "level": None, "score": None,
               "fields": {"name": [{"value": "Шаҳноза Раҳимова 🙂 ʻOʼ", "sources": [{"url": long_url}, "plain"]}],
                          "profiles": [{"sources": None}], "emails": None, "work": [{}]},
               "contacts": [{"kind": "weird", "value": None, "sources": None}],
               "chain": [{"path": None, "record": "r"}, {"path": [{}]}, {}],
               "why": ["w" * 3000], "contradictions": ["c"], "missing": ["location", "zzz"],
               "ai_review": {"verdict": None},
           }]}}
    card = person_card.build_card(run, "c1")
    assert person_card.card_pdf(card).startswith(b"%PDF")


def test_card_unknown_and_empty_run():
    with pytest.raises(person_card.CardError):
        person_card.build_card({}, "x")
    with pytest.raises(person_card.CardError):
        person_card.build_card({"result": {"candidates": None}}, "x")


# ---------- contact extractor ----------

def test_phone_noise_is_not_a_phone():
    noise = ("Order 2024-11-19 12:30, price 1 250 000 so'm, ID 307221939, INN 123456789, "
             "ISBN 978-3-16-148410-0, coords 41.311081 69.240562, version 1.2.3.4")
    assert contact_extract.phones_in(noise) == set()


def test_phone_formats_found():
    text = "Tel: +998 (90) 123-45-67, 90 765 43 21, +7 495 123-45-67"
    found = contact_extract.phones_in(text)
    assert "+998901234567" in found and "+998907654321" in found and "+74951234567" in found


def test_html_edge_cases():
    html = '''<html><body>
      <a href="mailto:Info@Site.UZ?subject=hi">mail</a>
      <a href="mailto:info@site.uz">again</a>
      <a href="tel:+998901234567">call</a>
      <p>Write to sales&#64;site.uz</p>
      <a href="https://t.me/site_uz?start=1">tg</a>
      <a href="https://apps.apple.com/app/id1">ios</a>
      <a href="https://mycdn.uz/">their cdn-named site</a>
      <a href="https://instagram.com/site.uz/">ig</a>
      <a href="/contact#form">Contact</a><a href="/about">About</a><a href="/news/1">n</a>
      <a href="//other.uz/">proto-relative</a>
      <script>var e="hidden@site.uz"</script>
    </body></html>'''
    contacts, links = contact_extract.contacts_from_html(html, "https://site.uz/")
    values = {(c["kind"], c["value"].lower()) for c in contacts}
    assert ("email", "info@site.uz") in values
    assert sum(1 for k, v in values if v == "info@site.uz") == 1
    assert ("email", "sales@site.uz") in values
    assert ("phone", "+998901234567") in values
    assert ("messenger", "https://t.me/site_uz") in values
    assert not any("apple" in v for _, v in values)
    assert ("email", "hidden@site.uz") not in values
    assert links[:2] == ["https://site.uz/contact", "https://site.uz/about"]


@pytest.mark.asyncio
async def test_extract_contacts_treats_robots_403_as_disallow_all(monkeypatch):
    calls = []

    async def fake_get(client, url, max_bytes=0, **kw):
        calls.append(url)
        req = httpx.Request("GET", url)
        if url.endswith("/robots.txt"):
            return httpx.Response(403, request=req)
        return httpx.Response(200, request=req, headers={"content-type": "text/html"},
                              text='<a href="mailto:a@site.uz">m</a>')

    monkeypatch.setattr(contact_extract, "safe_get", fake_get)
    monkeypatch.setattr(contact_extract, "PAUSE_SECONDS", 0)
    out = await contact_extract.extract_contacts("site.uz")
    # Python's RobotFileParser treats 401/403 robots.txt as "disallow all"
    assert out["pages"] == [], "robots.txt 401/403 should mean: do not crawl"


# ---------- orginfo ----------

def test_orginfo_parsers_on_junk():
    assert orginfo.parse_cards("") == []
    assert orginfo.parse_organization('<script type="application/ld+json">{bad</script>') is None
    assert orginfo.parse_organization('<script type="application/ld+json">[1, "x", null]</script>') is None
    assert orginfo.parse_organization(
        '<script type="application/ld+json">{"mainEntity": {"@type": "Organization", "name": "X"}}</script>'
    )["name"] == "X"


def test_orginfo_org_result_minimal_entity():
    result, pivots = orginfo.org_result("abc", {"employee": "junk", "founder": [None, 1], "address": None,
                                                "url": "http://WWW.Site.UZ/path"})
    assert result["url"].endswith("/abc/")
    assert {"type": "domain", "value": "site.uz", "via": "official_register"} in pivots


@pytest.mark.parametrize("name,company", [
    ("ALIYEV OKTAM", False), ("BANKOV AJAR", False), ("KARIMOV AJ", True), ('"ZIYO" MCHJ', True),
    ("XOLMATOV BANK", True),
])
def test_is_company_name(name, company):
    assert orginfo.is_company_name(name) is company


def test_display_name():
    assert orginfo.display_name("RO`ZIQULOV O`TKIR") == "Ro`ziqulov O`tkir"


def test_unhashable_values():
    scan = {"nodes": [{"key": ["a"]}, {"key": "b", "via": ["x"], "depth": "deep"}],
            "edges": [{"from": ["b"], "to": "b"}], "clusters": [{"members": [["b"]]}]}
    ET.fromstring(graph_export.to_graphml(scan).encode())
    graph_export.to_maltego_csv(scan)
