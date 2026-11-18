import pytest
from xposedornot.exceptions import APIError, NotFoundError, RateLimitError

from tools import email_intel
from tools.base import ToolError


@pytest.fixture(autouse=True)
def _no_hibp_key(monkeypatch):
    monkeypatch.delenv("HIBP_API_KEY", raising=False)

    async def no_catalog():
        return {}
    monkeypatch.setattr(email_intel, "breach_catalog", no_catalog)


CATALOG = {
    "adobe": {"title": "Adobe", "date": "2013-10-04", "count": 152445165, "domain": "adobe.com",
              "classes": ["Email addresses", "Password hints", "Passwords", "Usernames"]},
    "linkedin": {"title": "LinkedIn", "date": "2012-05-05", "count": 164611595, "domain": "linkedin.com",
                 "classes": ["Email addresses", "Passwords"]},
}


def test_describe_breaches_adds_dates_and_sensitive_types():
    text = email_intel.describe_breaches(["Adobe", "LinkedIn", "SomeForum"], CATALOG)
    assert text.startswith("Adobe (2013-10-04: Email addresses, Password hints, Passwords, Usernames)")
    assert "LinkedIn (2012-05-05: Email addresses, Passwords)" in text and "SomeForum" in text
    assert "Sensitive data types exposed across these breaches: Password hints, Passwords" in text


async def test_xposedornot_result_is_enriched(monkeypatch):
    async def catalog():
        return CATALOG
    monkeypatch.setattr(email_intel, "breach_catalog", catalog)
    monkeypatch.setattr(email_intel, "_xposedornot_check", lambda _e: ["Adobe"])
    entry, _w = await email_intel.lookup_breaches("a@example.com")
    assert "Adobe (2013-10-04" in entry["info"] and "HIBP public catalogue" in entry["info"]


async def test_xposedornot_reports_breaches(monkeypatch):
    names = [f"Breach{i}" for i in range(10)]
    monkeypatch.setattr(email_intel, "_xposedornot_check", lambda _e: names)
    entry, warning = await email_intel.lookup_breaches("a@example.com")
    assert warning is None
    assert entry["platform"] == "XposedOrNot Breaches"
    assert entry["info"].startswith("Found in 10 breach(es): Breach0")
    assert "+2 more" in entry["info"]


async def test_xposedornot_not_found_is_clean_result(monkeypatch):
    def not_found(_e):
        raise NotFoundError()
    monkeypatch.setattr(email_intel, "_xposedornot_check", not_found)
    entry, _ = await email_intel.lookup_breaches("a@example.com")
    # footprint's exposure score keys off this exact phrase
    assert "No known breaches" in entry["info"]


@pytest.mark.parametrize("exc", [RateLimitError(), APIError("boom", 500)])
async def test_xposedornot_errors_become_tool_errors(monkeypatch, exc):
    def fail(_e):
        raise exc
    monkeypatch.setattr(email_intel, "_xposedornot_check", fail)
    with pytest.raises(ToolError):
        await email_intel.lookup_breaches("a@example.com")


async def test_hibp_key_takes_precedence(monkeypatch):
    monkeypatch.setenv("HIBP_API_KEY", "k")

    async def fake_hibp(_e):
        return {"platform": "HIBP Breaches"}, None

    def must_not_call(_e):
        raise AssertionError("XposedOrNot should not be used when HIBP key is set")

    monkeypatch.setattr(email_intel, "lookup_hibp", fake_hibp)
    monkeypatch.setattr(email_intel, "_xposedornot_check", must_not_call)
    entry, _ = await email_intel.lookup_breaches("a@example.com")
    assert entry["platform"] == "HIBP Breaches"
