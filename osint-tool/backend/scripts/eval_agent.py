"""Measure Agent accuracy on cases with a known answer (ROADMAP 10.3 / 6.8).

    python scripts/eval_agent.py CASES.jsonl [--out report] [--sleep 20] [--only ID]

CASES.jsonl, one case per line:
    {"id": "torvalds",
     "text": "Linus Torvalds, 56 years old, from Portland",   # what a user would type
     "expect": ["https://github.com/torvalds"],                # the person's real profiles
     "source": "https://www.wikidata.org/wiki/Q34253",          # where the answer comes from
     "kind": "public"}                                          # public | consented

The answer must come from an open source (a knowledge base, the person's own
site) or from the person themselves. Cases about private people are run only
with their consent and are kept out of git (*.private.jsonl is ignored).

For each case the report gives the rank of the first candidate that holds an
expected profile, its level (strong/possible/weak), the strong leads that hold
none of them (false strong leads), expected profiles that were set aside as
"someone else" (the worst error), and the sources that did not answer.
Totals: hit@1, hit@3, MRR, false strong leads per case.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------- scoring (pure, tested) ----------------

def norm_url(url: str) -> str:
    """https://www.GitHub.com/Torvalds/ -> github.com/torvalds"""
    parsed = urlparse(str(url or "").strip())
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    path = parsed.path.rstrip("/").lower()
    return f"{host}{path}" if host else ""


def candidate_urls(candidate: dict) -> set[str]:
    urls = set()
    for values in (candidate.get("fields") or {}).values():
        for value in values or []:
            for src in value.get("sources") or []:
                if isinstance(src, dict) and src.get("url"):
                    urls.add(norm_url(src["url"]))
    for contact in candidate.get("contacts") or []:
        for src in contact.get("sources") or []:
            urls.add(norm_url(src))
    return urls - {""}


# profile URLs whose path is the handle: github.com/torvalds -> "torvalds"
_HANDLE_HOSTS = ("github.com", "gitlab.com", "x.com", "twitter.com", "instagram.com", "t.me", "keybase.io")


def expected_handles(expect: list[str]) -> set[str]:
    handles = set()
    for url in expect:
        host, _, path = norm_url(url).partition("/")
        if host in _HANDLE_HOSTS and path and "/" not in path:
            handles.add(path.lstrip("@"))
    return handles


def is_match(candidate: dict, expected: set[str], handles: set[str]) -> bool:
    """The candidate holds one of the person's profiles, or is built on their
    handle (the GitHub page itself may be missing when GitHub did not answer)."""
    if expected & candidate_urls(candidate):
        return True
    return any(m.get("type") == "username" and str(m.get("query") or "").lower() in handles
               for m in candidate.get("members") or [])


def score_case(case: dict, result: dict) -> dict:
    expected = {norm_url(u) for u in case.get("expect") or []} - {""}
    handles = expected_handles(case.get("expect") or [])
    candidates = result.get("candidates") or []
    rank, level = None, None
    for i, cand in enumerate(candidates, 1):
        if is_match(cand, expected, handles):
            rank, level = i, cand.get("level")
            break
    false_strong = [c.get("label") for c in candidates
                    if c.get("level") == "strong" and not is_match(c, expected, handles)]
    wrongly_set_aside = sorted({norm_url(a.get("url")) for c in candidates for a in c.get("set_aside") or []
                                if norm_url(a.get("url")) in expected})
    nodes = (result.get("scan") or {}).get("nodes") or []
    wrongly_set_aside += sorted({norm_url(a.get("url")) for n in nodes for a in n.get("set_aside") or []
                                 if norm_url(a.get("url")) in expected} - set(wrongly_set_aside))
    unchecked = sorted({s for n in nodes for s in n.get("unchecked") or []})
    row = {"id": case.get("id"), "rank": rank, "level": level, "candidates": len(candidates),
           "false_strong": false_strong, "wrongly_set_aside": wrongly_set_aside, "unchecked": unchecked}
    # why the right candidate got its level, and what beat it (10.5b); JSON report only
    detail = {}
    if rank:
        detail["match"] = explain(candidates[rank - 1])
    if rank != 1 and candidates:
        detail["top"] = explain(candidates[0])
    if detail:
        row["detail"] = detail
    return row


def explain(candidate: dict) -> dict:
    return {"label": candidate.get("label"), "score": candidate.get("score"), "level": candidate.get("level"),
            "why": candidate.get("why") or [], "contradictions": candidate.get("contradictions") or [],
            "missing": candidate.get("missing") or []}


def summarize(rows: list[dict]) -> dict:
    n = len(rows) or 1
    ranked = [r["rank"] for r in rows if r.get("rank")]
    return {
        "cases": len(rows),
        "hit@1": round(sum(1 for r in ranked if r == 1) / n, 3),
        "hit@3": round(sum(1 for r in ranked if r <= 3) / n, 3),
        "mrr": round(sum(1 / r for r in ranked) / n, 3),
        "correct_strong": round(sum(1 for r in rows if r.get("level") == "strong") / n, 3),
        "false_strong_per_case": round(sum(len(r["false_strong"]) for r in rows) / n, 3),
        "wrongly_set_aside": sum(len(r["wrongly_set_aside"]) for r in rows),
        "errors": sum(1 for r in rows if r.get("error")),
        "unchecked_cases": sum(1 for r in rows if r.get("unchecked")),
    }


def markdown(rows: list[dict], totals: dict) -> str:
    lines = ["# Agent accuracy", "",
             f"Cases: {totals['cases']} · hit@1 {totals['hit@1']:.0%} · hit@3 {totals['hit@3']:.0%} · "
             f"MRR {totals['mrr']} · correct as strong {totals['correct_strong']:.0%} · "
             f"false strong leads per case {totals['false_strong_per_case']} · "
             f"expected profiles set aside {totals['wrongly_set_aside']} · errors {totals['errors']} · "
             f"cases with unanswered sources {totals['unchecked_cases']}", "",
             "| Case | Rank | Level | Candidates | False strong | Set aside wrongly | Not checked | Seconds |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r.get('rank') or '—'} | {r.get('level') or '—'} | {r.get('candidates', 0)} | "
                     f"{', '.join(map(str, r.get('false_strong') or [])) or '—'} | "
                     f"{', '.join(r.get('wrongly_set_aside') or []) or '—'} | "
                     f"{', '.join(r.get('unchecked') or []) or '—'} | {r.get('seconds', '')}"
                     + (f" (error: {r['error']})" if r.get("error") else "") + " |")
    return "\n".join(lines) + "\n"


def load_cases(path: str) -> list[dict]:
    cases = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            case = json.loads(line)
            if not case.get("id") or not case.get("text") or not case.get("expect"):
                raise SystemExit(f"{path}:{n}: a case needs id, text and expect")
            cases.append(case)
    return cases


# ---------------- run ----------------

async def run(cases: list[dict], pause: float) -> list[dict]:
    from services.agent import run_agent

    rows = []
    for i, case in enumerate(cases):
        if i and pause:
            await asyncio.sleep(pause)          # gentle on the free sources (GitHub: 60/hour without a token)
        started = time.monotonic()
        try:
            result = await run_agent(case["text"])
            row = score_case(case, result)
        except Exception as exc:  # noqa: BLE001 - one failing case must not stop the evaluation
            row = {"id": case["id"], "rank": None, "level": None, "candidates": 0, "false_strong": [],
                   "wrongly_set_aside": [], "unchecked": [], "error": f"{type(exc).__name__}: {exc}"[:200]}
        row["seconds"] = round(time.monotonic() - started, 1)
        rows.append(row)
        print(f"[{i + 1}/{len(cases)}] {row['id']}: rank {row.get('rank') or '—'}, level {row.get('level') or '—'}",
              file=sys.stderr)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent accuracy on cases with a known answer")
    parser.add_argument("cases")
    parser.add_argument("--out", help="write OUT.md and OUT.json")
    parser.add_argument("--sleep", type=float, default=20.0, help="seconds between cases (default 20)")
    parser.add_argument("--only", action="append", help="run only these case ids")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    if args.only:
        cases = [c for c in cases if c["id"] in set(args.only)]
    rows = asyncio.run(run(cases, args.sleep))
    totals = summarize(rows)
    report = markdown(rows, totals)
    print(report)
    if args.out:
        with open(args.out + ".md", "w", encoding="utf-8") as fh:
            fh.write(report)
        with open(args.out + ".json", "w", encoding="utf-8") as fh:
            json.dump({"totals": totals, "cases": rows}, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
