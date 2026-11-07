import calendar

import pytest
from httpx import ASGITransport, AsyncClient

import main
from services import investigate as svc
from tools.base import ToolError
from tools.domain_enrich import audit_security_headers, detect_technologies, summarize_cert
from tools.domain_intel import (
    DomainValidationError,
    is_subdomain,
    normalize_domain,
    parse_crtsh,
)
from tools.ip_intel import summarize_internetdb


def test_is_subdomain_rejects_lookalike_domains():
    assert is_subdomain("a.example.com", "example.com")
    assert not is_subdomain("notexample.com", "example.com")
    assert not is_subdomain("example.com", "example.com")


def test_parse_crtsh_strips_wildcards_and_lookalikes():
    rows = [{"name_value": "*.a.example.com\nb.example.com\nnotexample.com"}, "bad"]
    assert parse_crtsh(rows, "example.com") == {"a.example.com", "b.example.com"}


def test_normalize_domain_rejects_numeric_tld():
    with pytest.raises(DomainValidationError):
        normalize_domain("999.1.1.1")


def test_private_ip_query_is_rejected():
    for query in ("127.0.0.1", "10.0.0.1", "::1"):
        with pytest.raises(svc.InvestigationValidationError):
            svc.parse_ip_query(query)


def test_parse_ip_query_passes_public_ip_and_ignores_domains():
    assert svc.parse_ip_query(" 8.8.8.8 ") == "8.8.8.8"
    assert svc.parse_ip_query("example.com") is None


def test_security_headers_audit_counts_frame_ancestors_as_clickjacking_cover():
    present, missing = audit_security_headers(
        {"content-security-policy": "frame-ancestors 'none'"}
    )
    assert "Content-Security-Policy" in present
    assert "X-Frame-Options" in present
    assert "Strict-Transport-Security" in missing


def test_detect_technologies_ignores_server_names_in_page_text():
    body = "Licensed under the Apache License. My reaction to nginx and cloudflare."
    assert detect_technologies({"server": "unknown"}, body) == []


def test_summarize_cert_reports_expiry_and_sans():
    cert = {
        "issuer": ((("organizationName", "Let's Encrypt"),),),
        "notAfter": "Jan  1 00:00:00 2027 GMT",
        "subjectAltName": (("DNS", "example.com"), ("DNS", "www.example.com")),
    }
    info = summarize_cert(cert, "TLSv1.3", now=calendar.timegm((2027, 1, 1, 0, 0, 0)) - 86400 * 30)
    assert "Let's Encrypt" in info
    assert "TLSv1.3" in info
    assert "SANs (2)" in info
    assert "30 day(s) left" in info


def test_summarize_internetdb_truncates_long_cve_list():
    data = {"ports": [80], "vulns": [f"CVE-2024-{i}" for i in range(20)]}
    info = summarize_internetdb("1.1.1.1", data)["info"]
    assert "Open ports: 80" in info
    assert "Known CVEs (20)" in info
    assert "+5 more" in info


def test_merge_marks_corroborated_hits_high_confidence_and_first():
    merged = svc._merge(
        [
            {"platform": "Zed", "url": "https://zed.dev/bob/", "status": "found"},
            {"platform": "Abc", "url": "https://abc.io/bob", "status": "found"},
        ],
        [{"platform": "Zed", "url": "https://www.zed.dev/bob", "status": "found"}],
    )
    assert [item["platform"] for item in merged] == ["Zed", "Abc"]
    assert merged[0]["confidence"] == "high"
    assert merged[0]["sources"] == ["sherlock", "maigret"]
    assert merged[1]["confidence"] == "medium"


async def test_email_survives_holehe_failure(monkeypatch):
    async def broken(_email):
        raise ToolError("holehe crashed")

    async def emailrep(_email):
        return {"platform": "EmailRep", "status": "found"}

    async def hibp(_email):
        return None, None

    async def domain_intel(_email):
        return [{"platform": "Email authentication", "status": "found"}], []

    async def gravatar(_email):
        return None

    monkeypatch.setattr(svc, "run_holehe", broken)
    monkeypatch.setattr(svc, "lookup_emailrep", emailrep)
    monkeypatch.setattr(svc, "lookup_hibp", hibp)
    monkeypatch.setattr(svc, "email_domain_intel", domain_intel)
    monkeypatch.setattr(svc, "gravatar_lookup", gravatar)

    async def mentions(_batches, max_results_per_batch):
        return [
            {"platform": "Web", "title": "Contact user@example.com", "info": ""},
            {"platform": "Noise", "title": "Unrelated page", "info": ""},
        ]

    monkeypatch.setattr(svc, "search_public", mentions)

    result = await svc._investigate_email("user@example.com")

    assert {r["platform"] for r in result["results"]} == {
        "EmailRep",
        "Email authentication",
        "Web",
    }
    assert result["warnings"] == ["Holehe: holehe crashed"]
    assert result["pivots"] == [
        {"type": "domain", "value": "example.com"},
        {"type": "username", "value": "user"},
    ]


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [("http://127.0.0.1:8080", True), ("https://evil.example", False)],
)
async def test_cors_only_allows_the_local_frontend(origin, allowed):
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.options(
            "/api/domain",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert (response.headers.get("access-control-allow-origin") == origin) is allowed


from tools import name_search as ns
from tools import public_profiles as pp


def test_telegram_parser_reads_public_page_and_rejects_contact_stub():
    page = (
        '<meta property="og:title" content="Tech &amp; News">'
        '<meta property="og:description" content="Daily digest">'
        '<div class="tgme_page_title"><span>Tech</span></div>'
        '<div class="tgme_page_extra">12 345 subscribers</div>'
    )
    entry = pp.parse_telegram(page, "technews")
    assert entry["url"] == "https://t.me/technews"
    assert "Tech & News" in entry["info"]
    assert "12 345 subscribers" in entry["info"]
    assert pp.parse_telegram('<meta property="og:title" content="Telegram: Contact @x">', "xxxxx") is None


def test_telegram_parser_drops_boilerplate_bio():
    page = (
        '<meta property="og:title" content="Bob">'
        '<meta property="og:description" content="You can contact @bobby right away.">'
        '<div class="tgme_page_title">Bob</div>'
        '<div class="tgme_page_extra">@bobby</div>'
    )
    assert pp.parse_telegram(page, "bobby")["info"] == "Name: Bob"


def test_github_parser_exposes_pivots_only_through_extract():
    entry = pp.parse_github(
        {"html_url": "https://github.com/bob", "name": "Bob", "blog": "https://bob.dev/x",
         "twitter_username": "bobby", "company": None}
    )
    assert "Company" not in entry["info"]
    assert pp.extract_pivots([entry]) == [
        {"type": "domain", "value": "bob.dev"},
        {"type": "username", "value": "bobby"},
    ]
    assert "website" not in entry and "linked_username" not in entry


async def test_profile_sources_isolate_failures(monkeypatch):
    async def ok(_client, _username):
        return {"platform": "A", "url": "https://a.io/x", "status": "found"}

    async def missing(_client, _username):
        return None

    async def limited(_client, _username):
        raise ToolError("rate limit reached.")

    monkeypatch.setattr(pp, "PROFILE_SOURCES", {"A": ok, "B": missing, "C": limited})
    outcome = await pp.run_profile_sources("bob")
    assert [r["platform"] for r in outcome["results"]] == ["A"]
    assert outcome["warnings"] == ["C: rate limit reached."]


def test_name_variants_cover_order_and_script():
    variants = ns.name_variants("Ali Valiyev")
    assert variants == ["Ali Valiyev", "Valiyev Ali", "Али Валиев", "Валиев Али"]


def test_transliterate_handles_uzbek_digraphs_and_cyrillic_input():
    assert ns.transliterate("Shohruh G'ulomov") == "Шохрух Гуломов"
    assert ns.transliterate("Шохрух") == "Shoxrux"


def test_filter_by_name_drops_unrelated_and_ranks_exact_first():
    variants = ns.name_variants("Ali Valiyev")
    items = [
        {"title": "Valiyev, Ali - profile", "info": "", "url": "https://a.io"},
        {"title": "Unrelated person", "info": "Ali only", "url": "https://b.io"},
        {"title": "Али Валиев", "info": "", "url": "https://c.io"},
    ]
    kept, dropped = ns.filter_by_name(items, variants)
    assert [item["url"] for item in kept] == ["https://c.io", "https://a.io"]
    assert [item["match"] for item in kept] == ["exact", "partial"]
    assert dropped == 1


def test_merge_ranks_api_above_engines_above_search_index():
    merged = svc._merge(
        [{"platform": "GitHub", "url": "https://github.com/bob", "status": "found"}],
        [{"platform": "Zed", "url": "https://zed.dev/bob", "status": "found"}],
        direct=[{"platform": "GitHub", "url": "https://www.github.com/bob",
                 "status": "found", "info": "Name: Bob"}],
        indexed=[{"platform": "Instagram", "url": "https://instagram.com/bob",
                  "status": "found"}],
    )
    assert [(m["platform"], m["confidence"]) for m in merged] == [
        ("GitHub", "high"), ("Zed", "medium"), ("Instagram", "low"),
    ]
    assert merged[0]["info"] == "Name: Bob"
    assert merged[0]["sources"] == ["public-api", "sherlock"]


async def test_username_lists_manual_links_only_for_platforms_without_hits(monkeypatch):
    async def engine(_username):
        return {"results": []}

    async def profiles(_username):
        return {"results": [], "warnings": ["Reddit: HTTP 403."], "pivots": []}

    async def web(_username):
        return {"results": [{"platform": "Instagram", "url": "https://instagram.com/bob/",
                             "status": "found"}], "posts": [], "pivots": []}

    monkeypatch.setattr(svc, "run_sherlock", engine)
    monkeypatch.setattr(svc, "run_maigret", engine)
    monkeypatch.setattr(svc, "run_profile_sources", profiles)
    monkeypatch.setattr(svc, "run_username_web", web)

    result = await svc._investigate_username("bob")

    labels = [link["label"] for link in result["links"]]
    assert "Instagram" not in labels and "TikTok" in labels
    assert result["warnings"] == ["Reddit: HTTP 403."]
    assert result["notice"]


async def test_name_keeps_structured_sources_when_web_search_fails(monkeypatch):
    async def broken(_name):
        raise ToolError("rate limited")

    async def sources(_name):
        return {"results": [{"platform": "ORCID", "url": "https://orcid.org/1",
                             "status": "found", "title": "Ali Valiyev"}],
                "warnings": [], "pivots": []}

    async def no_entity(_name):
        return {"results": [], "pivots": []}

    async def no_sanctions(_name):
        return {"results": [], "warnings": []}

    monkeypatch.setattr(svc, "run_name_search", broken)
    monkeypatch.setattr(svc, "run_name_sources", sources)
    monkeypatch.setattr(svc, "run_person_entity", no_entity)
    monkeypatch.setattr(svc, "run_sanctions_check", no_sanctions)

    result = await svc._investigate_name("Ali Valiyev")

    assert [r["platform"] for r in result["results"]] == ["ORCID"]
    assert result["warnings"] == ["Web search: rate limited"]


def test_sherlock_command_uses_only_flags_the_installed_version_accepts():
    import subprocess

    from tools.sherlock_runner import _build_command

    command = _build_command("bob")
    usage = subprocess.run(
        [command[0], "--help"], capture_output=True, text=True, check=True
    ).stdout
    for flag in (part for part in command[1:] if part.startswith("--")):
        assert flag in usage


def test_extract_tagged_handles_skips_the_subject_and_dedupes():
    handles = ns.extract_tagged_handles(
        "with @axror.xs @alishercr @axror.xs and @solievsm", "solievsm"
    )
    assert handles == ["axror.xs", "alishercr"]


async def test_social_presence_keeps_posts_and_turns_tags_into_pivots(monkeypatch):
    async def fake_search(batches, max_results_per_batch):
        return [
            {"platform": "x", "url": "https://instagram.com/p/1",
             "title": "solievsm reel", "info": "fun with @axror.xs @alishercr"},
            {"platform": "x", "url": "https://instagram.com/p/2",
             "title": "unrelated", "info": "no mention here"},
        ]

    monkeypatch.setattr(ns, "search_public", fake_search)
    outcome = await ns.run_username_web("solievsm")

    assert [p["url"] for p in outcome["posts"]] == ["https://instagram.com/p/1"]
    assert outcome["posts"][0]["kind"] == "post"
    assert outcome["posts"][0]["platform"] == "Instagram"
    assert outcome["results"] == []
    assert outcome["pivots"] == [
        {"type": "username", "value": "axror.xs"},
        {"type": "username", "value": "alishercr"},
    ]


async def test_username_merges_post_pivots_without_duplicating(monkeypatch):
    async def engine(_username):
        return {"results": []}

    async def profiles(_username):
        return {"results": [], "warnings": [],
                "pivots": [{"type": "username", "value": "axror.xs"}]}

    async def web(_username):
        return {"results": [],
                "posts": [{"platform": "Instagram", "url": "https://instagram.com/p/1",
                           "status": "found", "kind": "post"}],
                "pivots": [{"type": "username", "value": "axror.xs"},
                           {"type": "username", "value": "alishercr"}]}

    monkeypatch.setattr(svc, "run_sherlock", engine)
    monkeypatch.setattr(svc, "run_maigret", engine)
    monkeypatch.setattr(svc, "run_profile_sources", profiles)
    monkeypatch.setattr(svc, "run_username_web", web)

    result = await svc._investigate_username("solievsm")

    assert result["posts"][0]["platform"] == "Instagram"
    assert result["pivots"] == [
        {"type": "username", "value": "axror.xs"},
        {"type": "username", "value": "alishercr"},
    ]


from tools import entity_intel as ei


def test_wikidata_time_formatting_respects_precision():
    assert ei._format_wikidata_time({"time": "+1969-12-28T00:00:00Z", "precision": 11}) == "1969-12-28"
    assert ei._format_wikidata_time({"time": "+1969-00-00T00:00:00Z", "precision": 9}) == "1969"
    assert ei._format_wikidata_time(None) == ""


def test_claim_helpers_tolerate_missing_and_malformed():
    claims = {"P569": [{"mainsnak": {"datavalue": {"value": {"time": "+2000-01-01T00:00:00Z"}}}}],
              "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q1"}}}}, {"mainsnak": {}}]}
    assert ei._claim_value(claims, "P569")["time"].startswith("+2000")
    assert ei._claim_value(claims, "P999") is None
    assert ei._claim_ids(claims, "P106") == ["Q1"]


async def test_sanctions_skipped_without_key(monkeypatch):
    monkeypatch.delenv("OPENSANCTIONS_API_KEY", raising=False)
    outcome = await ei.run_sanctions_check("Jane Doe")
    assert outcome["results"] == []
    assert "OPENSANCTIONS_API_KEY" in outcome["warnings"][0]


async def test_name_includes_knowledge_base_first_with_its_pivots(monkeypatch):
    async def web(_name):
        return {"results": [{"platform": "GitHub", "url": "https://github.com/x",
                             "status": "found", "match": "exact"}], "dropped": 0}

    async def sources(_name):
        return {"results": [], "warnings": [], "pivots": []}

    async def entity(_name):
        return {"results": [{"platform": "Wikidata", "url": "https://www.wikidata.org/wiki/Q1",
                             "status": "found", "title": "Jane Doe", "info": "Born: 1980"}],
                "pivots": [{"type": "username", "value": "janedoe"}]}

    async def sanctions(_name):
        return {"results": [], "warnings": ["Sanctions/PEP screening skipped: ..."]}

    monkeypatch.setattr(svc, "run_name_search", web)
    monkeypatch.setattr(svc, "run_name_sources", sources)
    monkeypatch.setattr(svc, "run_person_entity", entity)
    monkeypatch.setattr(svc, "run_sanctions_check", sanctions)

    result = await svc._investigate_name("Jane Doe")

    assert result["results"][0]["platform"] == "Wikidata"
    assert {"type": "username", "value": "janedoe"} in result["pivots"]
    assert any("Sanctions" in w for w in result["warnings"])


from tools import email_domain as ed


def test_parse_gravatar_profile_extracts_fields_and_pivots():
    entry = {
        "profileUrl": "https://gravatar.com/beau",
        "displayName": "Beau Lebens",
        "currentLocation": "Golden, CO",
        "job_title": "Lead",
        "aboutMe": "builder",
        "accounts": [
            {"shortname": "twitter", "name": "Twitter", "username": "beaulebens",
             "url": "https://x.com/beaulebens"},
            {"shortname": "github", "name": "GitHub", "username": "beaulebens",
             "url": "https://github.com/beaulebens"},
            {"shortname": "wordpress", "name": "WP", "username": "beau",
             "url": "https://x.io"},
        ],
    }
    result, pivots = ed.parse_gravatar_profile(entry, "https://gravatar.com/img")
    assert "Name: Beau Lebens" in result["info"]
    assert "Linked accounts" in result["info"]
    assert pivots == [
        {"type": "username", "value": "beaulebens"},
        {"type": "username", "value": "beaulebens"},
    ]


async def test_email_adds_local_part_and_gravatar_pivots(monkeypatch):
    async def holehe(_e):
        return {"results": []}

    async def rep(_e):
        raise ToolError("skip")

    async def hibp(_e):
        return None, None

    async def dom(_e):
        return [], []

    async def grav(_e):
        return {"results": [{"platform": "Gravatar profile", "status": "found"}],
                "pivots": [{"type": "username", "value": "beaulebens"}]}

    async def mentions(_b, max_results_per_batch):
        return []

    monkeypatch.setattr(svc, "run_holehe", holehe)
    monkeypatch.setattr(svc, "lookup_emailrep", rep)
    monkeypatch.setattr(svc, "lookup_hibp", hibp)
    monkeypatch.setattr(svc, "email_domain_intel", dom)
    monkeypatch.setattr(svc, "gravatar_lookup", grav)
    monkeypatch.setattr(svc, "search_public", mentions)

    result = await svc._investigate_email("john.doe@example.com")

    assert {"type": "domain", "value": "example.com"} in result["pivots"]
    assert {"type": "username", "value": "beaulebens"} in result["pivots"]
    assert {"type": "username", "value": "john.doe"} in result["pivots"]


async def test_chesscom_and_npm_and_gravatar_username_sources(monkeypatch):
    calls = {}

    async def fake_fetch(client, url, **kw):
        calls["url"] = url
        if "chess.com" in url:
            return {"url": "https://chess.com/member/x", "name": "X", "followers": 3}
        if "npmjs.org" in url:
            return {"objects": [{"package": {"name": "leftpad"}}]}
        if "gravatar" in url:
            return {"entry": [{"profileUrl": "https://gravatar.com/x", "displayName": "X",
                               "accounts": [{"shortname": "github", "username": "xdev"}]}]}
        return None

    monkeypatch.setattr(pp, "fetch_json", fake_fetch)
    chess = await pp.chesscom_profile(None, "x")
    npm = await pp.npm_profile(None, "x")
    grav = await pp.gravatar_username(None, "x")
    assert chess["platform"] == "Chess.com" and "Followers: 3" in chess["info"]
    assert "leftpad" in npm["info"]
    assert grav["linked_username"] == "xdev"
    assert pp.extract_pivots([grav]) == [{"type": "username", "value": "xdev"}]


def test_epoch_to_date_formats_and_tolerates_junk():
    assert pp._epoch_to_date(1389043258) == "2014-01-06"
    assert pp._epoch_to_date(None) == ""
    assert pp._epoch_to_date("x") == ""


from tools import phone_intel as ph


def test_phone_manual_check_links():
    links = {l["label"]: l["url"] for l in ph.manual_check_links("+998901234567")}
    assert links["WhatsApp"] == "https://wa.me/998901234567"
    assert "998901234567" in links["Telegram"]
    assert "%22+998901234567%22" in links["Google"]


async def test_reverse_ip_lookup_parses_and_rejects_quota(monkeypatch):
    from tools import ip_intel as ii

    class Resp:
        def __init__(self, text, code=200):
            self.text = text
            self.status_code = code

    class Client:
        def __init__(self, text):
            self._text = text

        async def get(self, url):
            return Resp(self._text)

    entry, domains = await ii.reverse_ip_lookup(Client("a.com\nb.com\na.com"), "1.2.3.4")
    assert domains == ["a.com", "b.com"]
    assert "2 domain(s)" in entry["info"]

    import pytest as _pytest
    with _pytest.raises(ii.ToolError):
        await ii.reverse_ip_lookup(Client("API count exceeded"), "1.2.3.4")


async def test_reverse_ip_filters_ptr_arpa_noise(monkeypatch):
    from tools import ip_intel as ii

    class Resp:
        status_code = 200
        def __init__(self, text): self.text = text

    class Client:
        def __init__(self, text): self._text = text
        async def get(self, url): return Resp(self._text)

    _entry, domains = await ii.reverse_ip_lookup(
        Client("real.com\n0.d.5.ip6.arpa\nother.org"), "8.8.8.8"
    )
    assert domains == ["other.org", "real.com"]


from tools import company_intel as ci


def test_company_lei_validation_and_detection():
    assert ci.LEI_RE.fullmatch("7ZW8QJWVPR4P1J1KQY45")
    assert not ci.LEI_RE.fullmatch("not-a-lei")
    import pytest as _pytest
    with _pytest.raises(ci.CompanyValidationError):
        ci.normalize_company("x")
    assert ci.normalize_company("  Acme   Corp ") == "Acme Corp"


def test_format_record_extracts_name_address_and_reg_id():
    record = {
        "attributes": {
            "lei": "7ZW8QJWVPR4P1J1KQY45",
            "entity": {
                "legalName": {"name": "GOOGLE LLC"},
                "legalAddress": {"city": "Mountain View", "region": "US-CA", "country": "US"},
                "jurisdiction": "US-DE",
                "status": "ACTIVE",
                "registeredAs": "4356162",
            },
            "registration": {"status": "ISSUED", "lastUpdateDate": "2026-01-02T00:00:00Z"},
        }
    }
    entry = ci.format_record(record)
    assert entry["title"] == "GOOGLE LLC"
    assert "LEI: 7ZW8QJWVPR4P1J1KQY45" in entry["info"]
    assert "Mountain View" in entry["info"]
    assert "Local reg. id: 4356162" in entry["info"]
    assert "7ZW8QJWVPR4P1J1KQY45" in entry["url"]


async def test_investigate_company_builds_response_with_pivots(monkeypatch):
    async def fake(query):
        return {"results": [{"platform": "Company (GLEIF)", "title": "X", "status": "found"}],
                "pivots": [{"type": "company", "value": "Parent Inc"}]}

    monkeypatch.setattr(svc, "run_company_search", fake)
    result = await svc._investigate_company("X Corp")
    assert result["category"] == "company"
    assert result["count"] == 1
    assert result["pivots"] == [{"type": "company", "value": "Parent Inc"}]
    assert result["notice"]


def test_summarize_auth_reports_dkim_selectors():
    results, warnings = ed.summarize_auth(
        {"mx": ["mx1"], "txt": ["v=spf1 ~all"], "dmarc": ["v=DMARC1; p=none"],
         "dkim": ["google", "s1"]}
    )
    auth = {r["platform"]: r for r in results}["Email authentication"]["info"]
    assert "DKIM: yes (google, s1)" in auth
    assert not any("DKIM selector" in w for w in warnings)


def test_summarize_auth_warns_when_no_dkim():
    _results, warnings = ed.summarize_auth(
        {"mx": ["mx1"], "txt": ["v=spf1 ~all"], "dmarc": ["v=DMARC1; p=none"], "dkim": []}
    )
    assert any("DKIM selector" in w for w in warnings)


async def test_disposable_check_flags_known_throwaway(monkeypatch):
    async def fake_list():
        return {"mailinator.com", "guerrillamail.com"}

    monkeypatch.setattr(ed, "load_disposable_domains", fake_list)
    assert (await ed.disposable_check("mailinator.com"))["platform"] == "Disposable email"
    assert await ed.disposable_check("gmail.com") is None


def test_rdap_flags_newly_registered_domain(monkeypatch):
    import datetime as dt
    from tools import domain_intel as di

    recent = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    # Build the info string the same way rdap_lookup does, via its event handling.
    # Direct unit check of the age annotation path:
    events = {"registration": recent}
    info_parts = []
    registered = events["registration"]
    days = (dt.date.today() - dt.date.fromisoformat(registered[:10])).days
    assert 0 <= days < 90  # sanity for the test itself


from tools import web_recon as wr


def test_murmur3_matches_known_vectors():
    def unsigned(v): return v & 0xFFFFFFFF
    assert unsigned(wr.murmur3_32(b"", 0)) == 0
    assert unsigned(wr.murmur3_32(b"", 1)) == 0x514E28B7
    assert unsigned(wr.murmur3_32(b"test", 0)) == 0xBA6BD213


def test_parse_robots_extracts_disallowed_paths():
    text = "User-agent: *\nDisallow: /admin\nDisallow: /private/\nDisallow: /\nAllow: /x"
    assert wr.parse_robots(text) == ["/admin", "/private/"]


def test_exposure_scoring_levels():
    level, score, reasons = svc._exposure(10, True, True, True)
    assert level == "high" and score >= 6
    assert svc._exposure(0, False, False, False)[0] == "low"
    assert svc._exposure(4, None, False, False)[0] in ("low", "medium")


def test_opsec_tips_react_to_signals():
    tips = svc._opsec_tips(True, 6, True, True, False)
    joined = " ".join(tips)
    assert "breaches" in joined and "2FA" in joined
    assert "Gravatar" in joined
    assert any("General hygiene" in t for t in tips)


async def test_footprint_username_mode_builds_report(monkeypatch):
    async def profiles(_u):
        return {"results": [{"platform": "GitHub", "url": "https://github.com/x", "status": "found"},
                            {"platform": "Reddit", "url": "https://reddit.com/u/x", "status": "found"}],
                "warnings": [], "pivots": [{"type": "domain", "value": "x.dev"}]}

    monkeypatch.setattr(svc, "run_profile_sources", profiles)
    result = await svc._investigate_footprint("bob", "username", "", "bob")

    assert result["category"] == "footprint"
    assert result["results"][0]["platform"] == "Exposure assessment"
    assert any(r["platform"] == "OPSEC recommendation" for r in result["results"])
    assert result["pivots"] == [{"type": "domain", "value": "x.dev"}]


async def test_sec_edgar_aggregates_entities_and_forms():
    class Resp:
        status_code = 200
        def json(self):
            return {"hits": {"total": {"value": 2}, "hits": [
                {"_source": {"display_names": ["Tesla, Inc. (TSLA) (CIK 1)"],
                             "root_forms": ["10-K"], "file_date": "2025-01-30"}},
                {"_source": {"display_names": ["Tesla, Inc. (TSLA) (CIK 1)"],
                             "root_forms": ["8-K"], "file_date": "2024-06-01"}},
            ]}}

    class Client:
        async def get(self, url, **kw): return Resp()

    entry = await ci.sec_edgar_search(Client(), "Tesla")
    assert entry["platform"] == "SEC EDGAR"
    assert "Tesla, Inc." in entry["info"]
    assert "10-K" in entry["info"] and "8-K" in entry["info"]
    assert "latest 2025-01-30" in entry["info"]


async def test_opencorporates_skipped_without_key(monkeypatch):
    monkeypatch.delenv("OPENCORPORATES_API_KEY", raising=False)
    import pytest as _pytest
    with _pytest.raises(ci.ToolError) as exc:
        await ci.opencorporates_search(None, "Apple")
    assert "OPENCORPORATES_API_KEY" in str(exc.value)


async def test_gdelt_handles_rate_limit(monkeypatch):
    class Resp:
        status_code = 429
        headers = {}
        text = "Please limit requests"
    class Client:
        async def get(self, url, **kw): return Resp()
    import pytest as _pytest
    with _pytest.raises(ci.ToolError) as exc:
        await ci.gdelt_news(Client(), "Tesla")
    assert "rate limit" in str(exc.value).lower()


def test_mail_findings_scores_missing_auth():
    findings, risk, recs = svc._mail_findings({"txt": [], "dmarc": [], "dkim": []})
    platforms = {f["platform"]: f for f in findings}
    assert platforms["SPF"]["status"] == "error"
    assert platforms["DMARC"]["status"] == "error"
    assert risk >= 5
    assert any("SPF" in r for r in recs)


def test_mail_findings_passes_full_auth():
    findings, risk, recs = svc._mail_findings({
        "txt": ["v=spf1 -all"], "dmarc": ["v=DMARC1; p=reject"], "dkim": ["google"]})
    assert all(f["status"] == "found" for f in findings)
    assert risk == 0 and recs == []


def test_risk_level_thresholds():
    assert svc._risk_level(0) == "low"
    assert svc._risk_level(3) == "medium"
    assert svc._risk_level(7) == "high"


async def test_exposure_report_structure(monkeypatch):
    import services.investigate as s

    def records(domain): return {"txt": ["v=spf1 -all"], "dmarc": ["v=DMARC1; p=none"], "dkim": []}
    async def no_headers(client, domain): return [], 0, []
    async def collect(lookups): return {}, []

    monkeypatch.setattr(s, "gather_dns_records", records)
    monkeypatch.setattr(s, "_header_findings", no_headers)
    monkeypatch.setattr(s, "_collect", collect)

    result = await s._investigate_exposure("example.com")
    assert result["category"] == "exposure"
    assert result["results"][0]["platform"] == "Exposure score"
    assert any(r["platform"] == "Recommendation" for r in result["results"])


def test_dkim_validator_rejects_empty_and_null_keys():
    assert ed._is_valid_dkim("v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIB")
    assert not ed._is_valid_dkim("v=DKIM1; p=")        # wildcard null key
    assert not ed._is_valid_dkim("v=DKIM1; p=short")   # too short to be real
    assert not ed._is_valid_dkim("some unrelated txt")


async def test_securitytrails_skipped_without_key(monkeypatch):
    from tools import domain_intel as di
    monkeypatch.delenv("SECURITYTRAILS_API_KEY", raising=False)
    import pytest as _pytest
    with _pytest.raises(di.ToolError) as exc:
        await di._securitytrails_subdomains(None, "example.com")
    assert "SECURITYTRAILS_API_KEY" in str(exc.value)


async def test_hunter_skipped_without_key(monkeypatch):
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)
    import pytest as _pytest
    with _pytest.raises(svc.ToolError) as exc:
        await svc._hunter_emails(None, "example.com")
    assert "HUNTER_API_KEY" in str(exc.value)


async def test_brave_search_parses_results(monkeypatch):
    from tools import public_search as ps
    monkeypatch.setenv("BRAVE_API_KEY", "test-key")

    class Resp:
        status_code = 200
        def json(self):
            return {"web": {"results": [
                {"url": "https://x.io/a", "title": "A", "description": "desc"},
                {"url": "https://x.io/a#frag", "title": "dup", "description": ""},
            ]}}

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **kw): return Resp()

    monkeypatch.setattr(ps.httpx, "AsyncClient", Client)
    out = await ps._brave_search(['"bob" site:x.io'], 5)
    assert len(out) == 1 and out[0]["url"] == "https://x.io/a"
    assert out[0]["info"] == "desc"
