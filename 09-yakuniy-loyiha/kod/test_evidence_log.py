"""evidence_log.py testlari (9-modul). Tarmoqqa chiqmaydi: requests.get almashtiriladi.

Ishga tushirish:  python3 -m pytest -q 09-yakuniy-loyiha/kod
"""
import argparse
import hashlib
import json
import os

import pytest

import evidence_log as ev


class FakeResponse:
    def __init__(self, body: bytes, status=200, url="https://site.uz/", ctype="text/html; charset=utf-8"):
        self.body, self.status_code, self.url = body, status, url
        self.headers = {"content-type": ctype}
        self.closed = False

    def iter_content(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True


@pytest.fixture()
def fake_web(monkeypatch):
    responses = []

    def get(url, **kwargs):
        response = FakeResponse(b"<html>salom</html>", url=url)
        responses.append(response)
        return response

    monkeypatch.setattr(ev.requests, "get", get)
    return responses


def run(log, cmd, **kw):
    args = argparse.Namespace(log=str(log), **kw)
    {"add": ev.cmd_add, "import": ev.cmd_import, "grade": ev.cmd_grade, "list": ev.cmd_list,
     "verify": ev.cmd_verify, "report": ev.cmd_report}[cmd](args)


def add(log, url, **kw):
    opts = {"note": "", "grade": "", "fetch": False, "save": False}
    opts.update(kw)
    run(log, "add", url=url, **opts)


def test_add_fetch_save_and_hash(tmp_path, fake_web):
    log = tmp_path / "ish" / "dalillar.jsonl"
    log.parent.mkdir()
    add(log, "https://site.uz/", note="profil", grade="b2", save=True)
    entry = ev.load(log)[0]
    assert entry["id"] == "D001" and entry["grade"] == "B2"
    assert entry["sha256"] == hashlib.sha256(b"<html>salom</html>").hexdigest()
    assert entry["copy"] == os.path.join("dalillar", "D001.html")        # 8b.11: jurnalga nisbiy
    assert fake_web[0].closed                                              # 8b.14: ulanish yopildi


def test_verify_works_from_another_directory(tmp_path, fake_web, monkeypatch, capsys):
    work = tmp_path / "ish"
    work.mkdir()
    log = work / "dalillar.jsonl"
    add(log, "https://site.uz/", save=True)
    elsewhere = tmp_path / "boshqa"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    run(log, "verify")
    assert "muammo: 0" in capsys.readouterr().out
    (work / "dalillar" / "D001.html").write_bytes(b"o'zgartirilgan")
    with pytest.raises(SystemExit):
        run(log, "verify")
    assert "O'ZGARGAN" in capsys.readouterr().out


def test_large_page_is_marked_truncated(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "MAX_BYTES", 10)
    monkeypatch.setattr(ev.requests, "get", lambda url, **kw: FakeResponse(b"x" * 100, url=url))
    log = tmp_path / "d.jsonl"
    add(log, "https://site.uz/", fetch=True)
    entry = ev.load(log)[0]
    assert entry["truncated"] is True and entry["bytes"] == 10
    assert "(kesilgan)" in ev.report(ev.load(log))


def test_broken_lines_do_not_stop_the_tool(tmp_path, capsys):
    log = tmp_path / "d.jsonl"
    log.write_text("\n".join([
        json.dumps({"id": "D001", "url": "https://a.uz", "seen_at": "2026-11-21T10:00:00+00:00"}),
        "{buzilgan",
        json.dumps(["ro'yxat"]),
        json.dumps({"url": "https://b.uz"}),                 # id yo'q
        json.dumps({"id": "D009", "url": "javascript:alert(1)"}),
        json.dumps({"id": 7, "url": "https://c.uz"}),         # id son: matnga aylanadi
    ]) + "\n", encoding="utf-8")
    entries = ev.load(log)
    assert [e["id"] for e in entries] == ["D001", "7"]
    assert capsys.readouterr().err.count("buzilgan qator") == 4
    run(log, "list")
    assert ev.report(entries)
    assert ev.next_id(entries) == "D002"


def test_report_escapes_hostile_urls(tmp_path):
    entries = [{"id": "D001", "url": "https://a.uz/x y|z)(w]<b>", "platform": "Evil [x](y) | z",
                "note": "a|b\nc", "seen_at": "2026-11-21T10:00:00+00:00"}]
    row = next(line for line in ev.report(entries).splitlines() if line.startswith("| D001"))
    assert "https://a.uz/x%20y%7Cz%29%28w%5D%3Cb%3E" in row
    assert row.count(" | ") == 5                                       # jadval ustunlari buzilmadi
    assert "\n" not in row


def test_import_agent_run_merges_facts_and_skips_known(tmp_path):
    run_json = {"run": {"result": {"candidates": [{
        "id": "c1", "label": "@ali", "level": "strong",
        "fields": {"name": [{"value": "Ali Valiyev", "sources": [
                       {"platform": "GitHub", "url": "https://github.com/ali",
                        "retrieved_at": "2026-11-21T09:00:00+00:00"}]}],
                   "location": [{"value": "Toshkent", "sources": [
                       {"platform": "GitHub", "url": "https://github.com/ali"}]}]},
        "contacts": [{"kind": "email", "value": "ali@site.uz", "how": "page", "sources": ["https://site.uz/contact"]}],
    }]}, "nodes": [{"results": [{"platform": "X", "url": "https://x.com/other", "info": "noise"}]}]}}
    src = tmp_path / "agent.json"
    src.write_text(json.dumps(run_json), encoding="utf-8")
    log = tmp_path / "d.jsonl"
    run(log, "import", file=str(src), all=False)
    entries = ev.load(log)
    assert [e["url"] for e in entries] == ["https://github.com/ali", "https://site.uz/contact"]
    assert "name = Ali Valiyev" in entries[0]["note"] and "location = Toshkent" in entries[0]["note"]
    assert entries[0]["seen_at"] == "2026-11-21T09:00:00+00:00"
    run(log, "import", file=str(src), all=False)
    assert len(ev.load(log)) == 2                                     # takror qo'shilmaydi
    run(log, "import", file=str(src), all=True)
    assert "https://x.com/other" in {e["url"] for e in ev.load(log)}  # --all: butun graf


def test_grade_validation(tmp_path):
    log = tmp_path / "d.jsonl"
    add(log, "https://a.uz")
    run(log, "grade", id="d001", grade="c3")
    assert ev.load(log)[0]["grade"] == "C3"
    with pytest.raises(SystemExit):
        run(log, "grade", id="D001", grade="Z9")
    with pytest.raises(SystemExit):
        add(log, "ftp://a.uz")
