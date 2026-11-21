"""Dalil jurnali (9-modul): har bir topilma URL, UTC vaqt, SHA-256 va baho bilan.

Jurnal — oddiy JSON-lines fayl (har qatorda bitta dalil), shuning uchun uni
git'da saqlash, solishtirish va boshqa vositalarga berish oson.

Buyruqlar:
  add URL [--note ..] [--grade B2] [--fetch] [--save]   dalil qo'shish
  import FILE.json [--all]                              NEXUS eksportidan dalillar (Agent run:
                                                        faqat nomzodlar, --all bilan butun graf)
  grade ID B2                                           bahoni o'zgartirish
  list                                                  qisqa ro'yxat
  verify                                                saqlangan nusxalar o'zgarmaganmi
  report [-o FILE.md]                                   hisobot ilovasi (Markdown)

Vosita sahifani faqat o'qiydi (--fetch). Wayback'ga avtomatik yubormaydi:
arxiv havolasini o'zingiz ochasiz, chunki saqlash URL'ni ommaviy qiladi.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

HEADERS = {"User-Agent": "osint-course/1.0 (educational use)"}
DEFAULT_LOG = "dalillar.jsonl"
COPIES_DIR = "dalillar"
MAX_BYTES = 5 * 1024 * 1024
GRADE_RE = re.compile(r"^[A-F][1-6]$")
SOURCE_GRADES = {"A": "to'liq ishonchli", "B": "odatda ishonchli", "C": "ba'zan ishonchli",
                 "D": "odatda ishonchsiz", "E": "ishonchsiz", "F": "baholab bo'lmaydi"}
INFO_GRADES = {"1": "tasdiqlangan", "2": "ehtimol to'g'ri", "3": "balki to'g'ri",
               "4": "shubhali", "5": "ehtimoldan yiroq", "6": "baholab bo'lmaydi"}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_http(url: str) -> bool:
    return urlparse(str(url or "")).scheme in ("http", "https")


def check_grade(grade: str) -> str:
    grade = (grade or "").strip().upper()
    if grade and not GRADE_RE.match(grade):
        raise SystemExit(f"Baho noto'g'ri: {grade!r}. Masalan: A1, B2, C3 (manba A-F, ma'lumot 1-6).")
    return grade


def wayback_links(url: str) -> dict:
    return {"wayback_search": f"https://web.archive.org/web/*/{url}",
            "wayback_save": f"https://web.archive.org/save/{url}",
            "archive_today": f"https://archive.ph/newest/{quote(url, safe=':/')}"}


# ---- jurnal fayli ----

def load(log: Path) -> list[dict]:
    if not log.exists():
        return []
    entries = []
    for n, line in enumerate(log.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            entry = None
        if not isinstance(entry, dict) or not entry.get("id") or not is_http(entry.get("url")):
            # buzilgan yoki qo'lda noto'g'ri tahrirlangan qator dasturni to'xtatmaydi
            print(f"[!] {log}:{n} — buzilgan qator o'tkazib yuborildi", file=sys.stderr)
            continue
        entry["id"] = str(entry["id"])
        entries.append(entry)
    return entries


def save(log: Path, entries: list[dict]) -> None:
    tmp = log.with_suffix(log.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    tmp.replace(log)


def next_id(entries: list[dict]) -> str:
    numbers = [int(e["id"][1:]) for e in entries if re.fullmatch(r"D\d+", str(e.get("id", "")))]
    return f"D{(max(numbers) if numbers else 0) + 1:03d}"


# ---- sahifani o'qish ----

def fetch(url: str, copy_to: Path | None, log_dir: Path | None = None) -> dict:
    """Sahifani o'qiydi: status, hajm, SHA-256; --save bo'lsa nusxasini yozadi.

    Nusxa yo'li jurnal papkasiga nisbatan saqlanadi, shuning uchun `verify`
    istalgan papkadan ishlaydi. MAX_BYTES dan katta sahifa kesiladi va
    `truncated: true` belgisi qo'yiladi: hash faqat saqlangan qismniki."""
    truncated = False
    try:
        with requests.get(url, headers=HEADERS, timeout=15, stream=True) as r:
            body = b""
            for chunk in r.iter_content(64 * 1024):
                body += chunk
                if len(body) > MAX_BYTES:
                    body, truncated = body[:MAX_BYTES], True
                    break
            status, final_url = r.status_code, r.url
            content_type = r.headers.get("content-type", "").split(";")[0]
    except requests.RequestException as exc:
        return {"fetch_error": type(exc).__name__}
    info = {"http_status": status, "final_url": final_url, "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(), "content_type": content_type}
    if truncated:
        info["truncated"] = True
        print(f"    [!] sahifa {MAX_BYTES // (1024 * 1024)} MB dan katta: faqat boshi saqlandi, "
              "hash shu qismniki", file=sys.stderr)
    if copy_to is not None:
        copy_to.parent.mkdir(parents=True, exist_ok=True)
        copy_to.write_bytes(body)
        try:
            info["copy"] = str(copy_to.relative_to(log_dir)) if log_dir else str(copy_to)
        except ValueError:
            info["copy"] = str(copy_to.resolve())
    return info


def copy_path(entry: dict, log: Path) -> Path:
    """Nusxa fayli: jurnal papkasiga nisbatan (eski yozuvlar: joriy papkaga nisbatan)."""
    path = Path(entry["copy"])
    if path.is_absolute():
        return path
    beside_log = log.parent / path
    return beside_log if beside_log.exists() or not path.exists() else path


# ---- buyruqlar ----

def cmd_add(args) -> None:
    log = Path(args.log)
    entries = load(log)
    if not is_http(args.url):
        raise SystemExit("Faqat http(s) havola qo'shiladi.")
    entry = {"id": next_id(entries), "url": args.url, "seen_at": now_utc(), "source": "manual",
             "platform": urlparse(args.url).hostname or "", "note": args.note or "",
             "grade": check_grade(args.grade), **wayback_links(args.url)}
    if args.fetch or args.save:
        ext = ".html" if not args.url.lower().endswith(".pdf") else ".pdf"
        copy = log.parent / COPIES_DIR / f"{entry['id']}{ext}" if args.save else None
        entry.update(fetch(args.url, copy, log.parent))
    entries.append(entry)
    save(log, entries)
    print(f"[+] {entry['id']} qo'shildi: {args.url}")
    if entry.get("sha256"):
        print(f"    HTTP {entry['http_status']}, {entry['bytes']} bayt, sha256 {entry['sha256'][:16]}…")
    if entry.get("fetch_error"):
        print(f"    [!] sahifa o'qilmadi: {entry['fetch_error']}")
    print(f"    Arxivlash (o'zingiz oching): {entry['wayback_save']}")


def collect_nexus(data, found: list[dict], depth: int = 0) -> None:
    """NEXUS eksportidagi (natija, case, Agent) har bir manbali yozuv."""
    if depth > 8:
        return
    if isinstance(data, dict):
        url = data.get("url") or data.get("profile_url")
        if isinstance(url, str) and is_http(url) and (data.get("platform") or data.get("info")):
            found.append({"url": url, "platform": str(data.get("platform") or "")[:80],
                          "note": " ".join(str(data.get("info") or "").split())[:300],
                          "seen_at": data.get("retrieved_at") or "",
                          "reliability": data.get("reliability") or ""})
        for value in data.values():
            if isinstance(value, (dict, list)):
                collect_nexus(value, found, depth + 1)
    elif isinstance(data, list):
        for value in data:
            collect_nexus(value, found, depth + 1)


def agent_candidates(data) -> list[dict] | None:
    """Agent run JSON'idagi nomzodlar (GET /api/agent/{id}), aks holda None."""
    run = data.get("run", data) if isinstance(data, dict) else {}
    result = run.get("result") if isinstance(run, dict) else None
    candidates = result.get("candidates") if isinstance(result, dict) else None
    return candidates if isinstance(candidates, list) else None


def collect_candidates(candidates: list[dict], found: list[dict]) -> None:
    """Faqat nomzodlar: maydon manbalari va o'zi yozgan kontaktlar (butun skan grafi emas)."""
    for c in candidates:
        if not isinstance(c, dict):
            continue
        label = str(c.get("label") or c.get("id") or "")
        for field, values in (c.get("fields") or {}).items():
            for v in values if isinstance(values, list) else []:
                for src in (v.get("sources") or []) if isinstance(v, dict) else []:
                    if isinstance(src, dict) and is_http(src.get("url")):
                        found.append({"url": src["url"], "platform": str(src.get("platform") or "")[:80],
                                      "note": f"{label}: {field} = {v.get('value') or ''}"[:300],
                                      "seen_at": src.get("retrieved_at") or "", "reliability": c.get("level") or ""})
        for item in c.get("contacts") or []:
            for url in (item.get("sources") or []) if isinstance(item, dict) else []:
                if is_http(url):
                    found.append({"url": url, "platform": str(item.get("kind") or "contact"),
                                  "note": f"{label}: {item.get('kind')} {item.get('value')} ({item.get('how') or ''})"[:300],
                                  "seen_at": "", "reliability": c.get("level") or ""})


def cmd_import(args) -> None:
    log = Path(args.log)
    entries = load(log)
    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Fayl o'qilmadi: {exc}")
    found: list[dict] = []
    candidates = agent_candidates(data)
    if candidates is not None and not args.all:
        collect_candidates(candidates, found)
        print(f"Agent run: {len(candidates)} ta nomzodning manbalari (butun graf uchun: --all)")
    else:
        collect_nexus(data, found)
    known = {e["url"] for e in entries}
    fresh: dict[str, dict] = {}                 # URLs added by this import
    added = merged = 0
    for item in found:
        url = item["url"]
        if url in fresh:                        # same page, another fact: keep both notes
            entry = fresh[url]
            if item["note"] and item["note"] not in entry["note"]:
                entry["note"] = (entry["note"] + "; " + item["note"]).strip("; ")[:600]
                merged += 1
            continue
        if url in known:
            continue
        known.add(url)
        entry = {"id": next_id(entries), "source": "nexus", "grade": "",
                 **item, "seen_at": item["seen_at"] or now_utc(),
                 "imported_at": now_utc(), **wayback_links(url)}
        entries.append(entry)
        fresh[url] = entry
        added += 1
    save(log, entries)
    print(f"[+] {added} ta yangi dalil import qilindi"
          + (f", {merged} ta fakt mavjud sahifaga qo'shildi" if merged else "")
          + f" (jurnalda bor edi: {len({i['url'] for i in found}) - added}).")
    print("    Baholang: evidence_log.py grade D001 B2")


def cmd_grade(args) -> None:
    log = Path(args.log)
    entries = load(log)
    for e in entries:
        if e.get("id") == args.id.upper():
            e["grade"] = check_grade(args.grade)
            save(log, entries)
            print(f"[+] {e['id']}: {e['grade']}")
            return
    raise SystemExit(f"{args.id} topilmadi.")


def cmd_list(args) -> None:
    entries = load(Path(args.log))
    if not entries:
        print("Jurnal bo'sh.")
    for e in entries:
        print(f"{e['id']}  {e.get('grade') or '--'}  {e.get('seen_at', '')[:16]}  {e['url']}")


def cmd_verify(args) -> None:
    log = Path(args.log)
    entries = load(log)
    bad = checked = 0
    for e in entries:
        if not e.get("copy"):
            continue
        checked += 1
        path = copy_path(e, log)
        if not path.exists():
            print(f"[!] {e['id']}: nusxa yo'q ({path})")
            bad += 1
        elif hashlib.sha256(path.read_bytes()).hexdigest() != e.get("sha256"):
            print(f"[!] {e['id']}: nusxa O'ZGARGAN ({path})")
            bad += 1
    print(f"Tekshirildi: {checked} ta nusxa, muammo: {bad}")
    if bad:
        sys.exit(1)


def _cell(text) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


_MD_URL_UNSAFE = {" ": "%20", "|": "%7C", "(": "%28", ")": "%29", "<": "%3C", ">": "%3E",
                  "[": "%5B", "]": "%5D", "\n": "", "\r": ""}


def _md_url(url: str) -> str:
    """Import qilingan URL ishonchsiz: jadval va havolani buzadigan belgilar kodlanadi."""
    return "".join(_MD_URL_UNSAFE.get(ch, ch) for ch in str(url))


def report(entries: list[dict]) -> str:
    lines = ["# Ilova: dalil jurnali", "",
             f"Tuzilgan: {now_utc()} · dalillar: {len(entries)}", "",
             "| ID | Baho | Ko'rilgan (UTC) | Manba | Izoh | SHA-256 |",
             "|----|------|-----------------|-------|------|---------|"]
    for e in entries:
        label = _cell(e.get("platform") or urlparse(e["url"]).hostname).replace("[", "(").replace("]", ")")
        link = f"[{label}]({_md_url(e['url'])})"
        sha = (e.get("sha256") or "")[:12] + (" (kesilgan)" if e.get("truncated") else "")
        lines.append(f"| {e['id']} | {e.get('grade') or '—'} | {_cell(e.get('seen_at', '')[:16]).replace('T', ' ')} "
                     f"| {link} | {_cell(e.get('note'))[:160]} | {sha} |")
    ungraded = [e["id"] for e in entries if not e.get("grade")]
    lines += ["", "## Baholash", "",
              "Manba: " + ", ".join(f"{k} — {v}" for k, v in SOURCE_GRADES.items()), "",
              "Ma'lumot: " + ", ".join(f"{k} — {v}" for k, v in INFO_GRADES.items()), ""]
    if ungraded:
        lines += [f"⚠️ Baholanmagan: {', '.join(ungraded)}", ""]
    lines += ["SHA-256 — `--save` bilan saqlangan nusxaning hash'i; `verify` buyrug'i nusxa "
              "o'zgarmaganini tekshiradi.", ""]
    return "\n".join(lines)


def cmd_report(args) -> None:
    text = report(load(Path(args.log)))
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"[+] Hisobot: {args.output}")
    else:
        print(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dalil jurnali (9-modul, yakuniy loyiha)")
    parser.add_argument("--log", default=DEFAULT_LOG, help=f"jurnal fayli (standart: {DEFAULT_LOG})")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="dalil qo'shish")
    p.add_argument("url")
    p.add_argument("--note", help="nima uchun muhim")
    p.add_argument("--grade", default="", help="Admiralty bahosi, masalan B2")
    p.add_argument("--fetch", action="store_true", help="sahifani o'qib SHA-256 hisoblash")
    p.add_argument("--save", action="store_true", help="nusxasini dalillar/ papkasiga saqlash")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("import", help="NEXUS JSON eksportidan import")
    p.add_argument("file")
    p.add_argument("--all", action="store_true", help="Agent run'da butun skan grafini olish")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("grade", help="dalilni baholash")
    p.add_argument("id")
    p.add_argument("grade")
    p.set_defaults(func=cmd_grade)

    sub.add_parser("list", help="ro'yxat").set_defaults(func=cmd_list)
    sub.add_parser("verify", help="nusxalar o'zgarmaganini tekshirish").set_defaults(func=cmd_verify)

    p = sub.add_parser("report", help="Markdown ilova")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
