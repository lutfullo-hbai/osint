from tools.domain_enrich import detect_technologies
from tools.email_domain import summarize_auth


def test_summarize_auth_reports_present_spf_and_dmarc():
    results, warnings = summarize_auth(
        {
            "mx": ["mx1.example.com", "mx2.example.com"],
            "txt": ["v=spf1 include:_spf.example.com ~all"],
            "dmarc": ["v=DMARC1; p=reject; rua=mailto:dmarc@example.com"],
        }
    )

    platforms = {item["platform"]: item for item in results}
    assert "MX records" in platforms
    assert "mx1.example.com" in platforms["MX records"]["info"]
    auth_info = platforms["Email authentication"]["info"]
    assert "SPF: yes" in auth_info
    assert "DMARC: yes" in auth_info
    assert warnings == []


def test_summarize_auth_warns_when_records_are_missing():
    results, warnings = summarize_auth({"mx": [], "txt": [], "dmarc": []})

    platforms = {item["platform"]: item for item in results}
    assert "MX records" not in platforms
    assert "SPF: no" in platforms["Email authentication"]["info"]
    assert "DMARC: no" in platforms["Email authentication"]["info"]
    assert len(warnings) == 3


def test_detect_technologies_matches_headers_and_body():
    technologies = detect_technologies(
        {"server": "nginx", "x-powered-by": "PHP/8.1"},
        "<link href='/wp-content/style.css'>",
    )

    assert "nginx" in technologies
    assert "PHP" in technologies
    assert "WordPress" in technologies


def test_detect_technologies_returns_empty_for_plain_site():
    assert detect_technologies({"server": "unknown"}, "<html></html>") == []
