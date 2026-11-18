"""3b.3: DNS history from our own lookups + Mnemonic + Robtex."""
import json
import time

import pytest

from tools import passive_dns as pdns

MNEMONIC = {"data": [
    {"rrtype": "a", "answer": "104.26.12.83", "firstSeenTimestamp": 1743770379660,
     "lastSeenTimestamp": 1764445080484, "times": 6},
    {"rrtype": "a", "answer": "185.8.212.10", "firstSeenTimestamp": 1600000000000,
     "lastSeenTimestamp": 1650000000000, "times": 3},
]}
ROBTEX = "\n".join(json.dumps(x) for x in [
    {"rrname": "kun.uz", "rrdata": "jeremy.ns.cloudflare.com", "rrtype": "NS",
     "time_first": 1632553330, "time_last": 1794983390, "count": 3},
    {"rrname": "kun.uz", "rrdata": "185.8.212.10", "rrtype": "A",
     "time_first": 1550000000, "time_last": 1640000000, "count": 2},
]) + "\nnot json"


def test_parsers():
    assert pdns.parse_mnemonic(MNEMONIC)[0] == ("a", "104.26.12.83", 1743770379.66, 1764445080.484, 6)
    rows = pdns.parse_robtex(ROBTEX)
    assert len(rows) == 2 and rows[0][0] == "NS"


def test_history_merges_sources_and_widens_dates(tmp_path):
    db = str(tmp_path / "pdns.db")
    pdns.upsert("kun.uz", pdns.parse_mnemonic(MNEMONIC), "mnemonic", db)
    pdns.upsert("kun.uz", pdns.parse_robtex(ROBTEX), "robtex", db)
    rows = {(r["rrtype"], r["value"]): r for r in pdns.history("kun.uz", db)}
    old_ip = rows[("A", "185.8.212.10")]
    assert old_ip["first"] == 1550000000 and old_ip["last"] == 1650000000
    assert set(old_ip["sources"].split(",")) == {"mnemonic", "robtex"}
    assert ("NS", "jeremy.ns.cloudflare.com") in rows


def test_own_observations_accumulate(tmp_path):
    db = str(tmp_path / "pdns.db")
    pdns.record_self("example.uz", [("A", ["1.2.3.4"]), ("MX", ["mx.example.uz."])], db)
    pdns.record_self("example.uz", [("A", ["1.2.3.4"])], db)
    rows = pdns.history("example.uz", db)
    assert {(r["rrtype"], r["value"]) for r in rows} == {("A", "1.2.3.4"), ("MX", "mx.example.uz")}


@pytest.mark.asyncio
async def test_lookup_uses_cache_and_robtex_budget(tmp_path, monkeypatch):
    db = str(tmp_path / "pdns.db")
    calls = {"mnemonic": 0, "robtex": 0}

    async def fake_mnemonic(client, domain):
        calls["mnemonic"] += 1
        return pdns.parse_mnemonic(MNEMONIC)

    async def fake_robtex(client, domain):
        calls["robtex"] += 1
        return pdns.parse_robtex(ROBTEX)

    monkeypatch.setattr(pdns, "_mnemonic", fake_mnemonic)
    monkeypatch.setattr(pdns, "_robtex", fake_robtex)
    entry, notes = await pdns.lookup("kun.uz", db)
    await pdns.lookup("kun.uz", db)                     # within 7 days: no new calls
    assert calls == {"mnemonic": 1, "robtex": 1} and notes == []
    assert "no longer current" in entry["info"] and "185.8.212.10" in entry["info"]
    assert entry["source"] == "passive_dns"


@pytest.mark.asyncio
async def test_robtex_hourly_budget(monkeypatch):
    monkeypatch.setattr(pdns, "_robtex_calls", __import__("collections").deque(
        [time.monotonic()] * pdns.ROBTEX_PER_HOUR))
    assert await pdns._robtex(None, "kun.uz") is None   # budget used: skipped, no request
