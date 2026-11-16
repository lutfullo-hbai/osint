"""Measure record-linkage quality on the labelled gold set.

    python scripts/eval_linkage.py [path/to/gold.json]

Each case is a pair of nodes with the true answer (same person or not).
Prints precision (merges that were right), recall (true pairs that were
merged) and every miss, so a weight change can be judged by numbers.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.correlate import correlate  # noqa: E402

DEFAULT_GOLD = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "linkage_gold.json")


def evaluate(cases: list[dict]) -> dict:
    tp = fp = fn = tn = 0
    misses = []
    for case in cases:
        out = correlate(case["nodes"])
        keys = [n["key"] for n in case["nodes"]]
        merged = any(all(k in c["members"] for k in keys) for c in out["clusters"])
        if merged and case["same"]:
            tp += 1
        elif merged:
            fp += 1
            misses.append(("FALSE MERGE", case))
        elif case["same"]:
            fn += 1
            misses.append(("MISSED", case))
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "misses": misses}


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GOLD
    with open(path, encoding="utf-8") as fh:
        cases = json.load(fh)
    r = evaluate(cases)
    print(f"cases={len(cases)} tp={r['tp']} fp={r['fp']} fn={r['fn']} tn={r['tn']}")
    print(f"precision={r['precision']:.2f} recall={r['recall']:.2f}")
    for kind, case in r["misses"]:
        print(f"  {kind}: {case['id']} — {case['desc']}")


if __name__ == "__main__":
    main()
