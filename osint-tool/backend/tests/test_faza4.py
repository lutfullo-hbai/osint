"""Faza 4: in-process Holehe — safety policy, three states, health, canary."""
import pytest

from services import monitor
from tools import holehe_runner as hr


def _mod(name, method="register", category="social_media", exists=False, rate_limit=False,
         domain=None, raises=False):
    async def func(email, client, out):
        if raises:
            raise RuntimeError("site changed")
        out.append({"name": name, "domain": domain or f"{name}.com", "method": method,
                    "rateLimit": rate_limit, "exists": exists})
    return hr.HoleheModule(name, category, method, func)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(hr, "_memory_health", {})
    monkeypatch.setattr(hr, "MIN_INTERVAL_PER_SITE_SECONDS", 0)

    async def no_redis():
        return None
    monkeypatch.setattr(hr, "get_client", no_redis)
    for env in ("HOLEHE_ALLOW_LOGIN", "HOLEHE_INCLUDE_ADULT"):
        monkeypatch.delenv(env, raising=False)


def test_policy_never_runs_password_recovery(monkeypatch):
    assert not hr.policy_allows(_mod("samsung", method="password recovery"))
    monkeypatch.setenv("HOLEHE_ALLOW_LOGIN", "1")
    monkeypatch.setenv("HOLEHE_INCLUDE_ADULT", "1")
    assert not hr.policy_allows(_mod("samsung", method="password recovery"))


def test_policy_login_and_adult_are_opt_in(monkeypatch):
    assert not hr.policy_allows(_mod("amazon", method="login"))
    assert not hr.policy_allows(_mod("xsite", category="porn"))
    assert hr.policy_allows(_mod("github"))
    monkeypatch.setenv("HOLEHE_ALLOW_LOGIN", "1")
    assert hr.policy_allows(_mod("amazon", method="login"))


def test_real_module_list_excludes_known_recovery_modules():
    names = {m.name for m in hr.available_modules() if hr.policy_allows(m)}
    assert not names & {"adobe", "mail_ru", "odnoklassniki", "samsung"}
    assert {"github", "instagram", "spotify"} <= names


def test_classify_three_states():
    assert hr.classify([{"exists": True, "rateLimit": False}])[0] == "used"
    assert hr.classify([{"exists": False, "rateLimit": False}])[0] == "not_used"
    assert hr.classify([{"exists": False, "rateLimit": True}])[0] == "unknown"
    assert hr.classify([])[0] == "unknown"


def test_module_paused_after_only_unknown_answers():
    record = None
    for _ in range(hr.UNKNOWN_PAUSE_AFTER):
        record = hr._next_record(record, "unknown", 1000.0)
    assert hr.is_paused(record, now=1001.0)
    assert not hr.is_paused(record, now=1000.0 + hr.UNKNOWN_PAUSE_SECONDS + 1)
    ok = hr._next_record(None, "not_used", 1000.0)
    assert not hr.is_paused(ok, now=1001.0)


@pytest.mark.asyncio
async def test_run_holehe_reports_signals_and_summary(monkeypatch):
    modules = (
        _mod("spotify", exists=True, domain="spotify.com"),
        _mod("github", exists=False),
        _mod("discord", rate_limit=True, domain="discord.com"),
        _mod("broken", raises=True),
        _mod("samsung", method="password recovery", exists=True),
    )
    monkeypatch.setattr(hr, "available_modules", lambda: modules)
    out = await hr.run_holehe("jane@example.com")
    assert out["used"] == ["spotify.com"]
    assert set(out["unknown"]) == {"discord.com", "broken"}
    signal = out["results"][0]
    assert signal["platform"] == "spotify.com" and "unconfirmed" in signal["info"]
    summary = out["results"][-1]
    assert summary["source"] == "run_summary"
    assert "1 say registered, 1 say not registered, 2 could not be checked" in summary["info"]
    assert all("samsung" not in r["platform"] for r in out["results"])


@pytest.mark.asyncio
async def test_run_holehe_skips_paused_modules(monkeypatch):
    modules = (_mod("spotify", exists=True, domain="spotify.com"), _mod("github"))
    monkeypatch.setattr(hr, "available_modules", lambda: modules)
    hr._memory_health["spotify"] = {"paused_until": 9e12, "pause_reason": "test"}
    out = await hr.run_holehe("jane@example.com")
    assert out["used"] == [] and out["checked"] == 1
    assert "1 site check(s) paused" in out["results"][-1]["info"]


@pytest.mark.asyncio
async def test_run_holehe_fails_when_nothing_answers(monkeypatch):
    monkeypatch.setattr(hr, "available_modules", lambda: (_mod("a", rate_limit=True),))
    with pytest.raises(hr.ToolError):
        await hr.run_holehe("jane@example.com")


@pytest.mark.asyncio
async def test_canary_pauses_false_positive_modules(monkeypatch):
    modules = (_mod("liar", exists=True), _mod("honest", exists=False))
    monkeypatch.setattr(hr, "available_modules", lambda: modules)
    out = await hr.run_canary()
    assert out["false_positives"] == ["liar"]
    assert hr.is_paused(hr._memory_health["liar"])
    assert not hr.is_paused(hr._memory_health["honest"])


def test_holehe_summary_is_not_watched():
    sig = monitor.signature_items({"results": [
        {"platform": "spotify.com", "url": "https://spotify.com", "status": "registered", "info": "x"},
        {"platform": "Registration checks (Holehe)", "url": "u", "status": "info",
         "source": "run_summary", "info": "changes every run"},
    ]})
    assert len(sig) == 1 and sig[0].startswith("spotify.com|")
