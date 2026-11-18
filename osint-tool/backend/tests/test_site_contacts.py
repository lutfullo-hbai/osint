"""3b.4: published contacts from security.txt, DNS and a polite crawl."""
import httpx
import pytest

from services import correlate as corr
from tools import domain_emails as de
from tools import site_contacts as sc


def test_parsers():
    assert sc.parse_security_txt("Contact: mailto:security@acme.uz\nExpires: 2027") == {"security@acme.uz"}
    assert sc.parse_dmarc("v=DMARC1; p=none; rua=mailto:dmarc@acme.uz,mailto:x@vendor.com!10m") == \
        {"dmarc@acme.uz", "x@vendor.com"}
    assert sc.soa_rname_to_email("hostmaster.acme.uz.") == "hostmaster@acme.uz"
    assert sc.soa_rname_to_email("john\\.doe.acme.uz.") == "john.doe@acme.uz"
    assert sc.emails_in("write to info [at] acme [dot] uz or logo@2x.png") == {"info@acme.uz"}


def test_contact_links_same_host_only():
    html = ('<a href="/kontakt">Kontaktlar</a><a href="/news">News</a>'
            '<a href="https://other.uz/contact">x</a><a href="/about-us">Biz haqimizda</a>')
    assert sc.contact_links(html, "https://acme.uz/") == ["https://acme.uz/kontakt", "https://acme.uz/about-us"]


@pytest.mark.asyncio
async def test_crawl_obeys_robots_and_reads_contact_page(monkeypatch):
    pages = {
        "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /about-us\n"),
        "/": (200, "text/html", '<a href="/kontakt">Kontakt</a><a href="/about-us">Biz haqimizda</a>'),
        "/kontakt": (200, "text/html", '<a href="mailto:info@acme.uz">Mail</a> Direktor: a.karimov@acme.uz'),
        "/about-us": (200, "text/html", "secret@acme.uz"),
    }
    requested = []

    async def fake_safe_get(client, url):
        path = httpx.URL(url).path
        requested.append(path)
        status, ctype, body = pages[path]
        return httpx.Response(status, headers={"content-type": ctype}, text=body,
                              request=httpx.Request("GET", url))
    monkeypatch.setattr(sc, "safe_get", fake_safe_get)
    monkeypatch.setattr(sc, "PAUSE_SECONDS", 0)
    found, notes = await sc.crawl_contacts("acme.uz")
    emails = {e for e, _how, _url in found}
    assert emails == {"info@acme.uz", "a.karimov@acme.uz"}
    assert "/about-us" not in requested and any("robots.txt disallows" in n for n in notes)


@pytest.mark.asyncio
async def test_crawl_stops_at_a_challenge(monkeypatch):
    async def fake_safe_get(client, url):
        body = "" if url.endswith("robots.txt") else "<title>Just a moment...</title> cf-chl captcha"
        return httpx.Response(200 if url.endswith("robots.txt") else 403,
                              headers={"content-type": "text/html"}, text=body,
                              request=httpx.Request("GET", url))
    monkeypatch.setattr(sc, "safe_get", fake_safe_get)
    found, notes = await sc.crawl_contacts("acme.uz")
    assert found == [] and any("anti-bot" in n for n in notes)


def test_dns_contacts_are_not_identity_evidence():
    entry = de._entry("dns@cloudflare.com", "DNS zone administrator (SOA record)", "DNS SOA a.uz", "a.uz")
    assert entry["source"] == "dns_contact" and "another provider" in entry["info"]
    assert "administrative address" in entry["info"] and "personal" not in entry["info"]
    nodes = [{"key": "host:a.uz", "type": "domain", "query": "a.uz", "results": [entry]},
             {"key": "host:b.uz", "type": "domain", "query": "b.uz",
              "results": [de._entry("dns@cloudflare.com", "DNS zone administrator (SOA record)", "DNS SOA b.uz", "b.uz")]}]
    assert corr.correlate(nodes)["cluster_count"] == 2      # a shared DNS provider links nothing
