import pytest
from xposedornot.exceptions import APIError, NotFoundError, RateLimitError

from tools import email_intel
from tools.base import ToolError


@pytest.fixture(autouse=True)
def _no_hibp_key(monkeypatch):
    monkeypatch.delenv("HIBP_API_KEY", raising=False)


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
