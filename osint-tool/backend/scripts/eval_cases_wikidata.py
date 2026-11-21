"""Build public evaluation cases from Wikidata (ROADMAP 10.3).

    python scripts/eval_cases_wikidata.py > eval/agent_cases.public.jsonl

Only well-known technologists who present their work publicly are listed
(QIDS below, chosen by hand): no politicians, no people known for a criminal
case, nobody deceased. For each, Wikidata gives the GitHub username
(property P2037), the birth year (P569) and the residence (P551); the case
text is what a user would type ("Name, N years old, from Town") and the
expected answer is the GitHub profile, with the Wikidata page as its source.

Bias to keep in mind: the Agent also asks Wikidata, so these cases measure the
"well-known person" path. Cases about ordinary people (the main use) must come
from the people themselves, with consent: put them in a *.private.jsonl file
(ignored by git).
"""
from __future__ import annotations

import json
import sys
from datetime import date

import httpx

ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "osint-tool-eval/1.0 (self-hosted research; low volume)"
QIDS = [
    "Q80", "Q34253", "Q30942", "Q92620", "Q1107006", "Q7637", "Q295981", "Q16197959", "Q92648",
    "Q92748", "Q62849", "Q316544", "Q517764", "Q56037405", "Q76448707", "Q100604534", "Q370733",
    "Q263175", "Q15778935", "Q3037998", "Q92955", "Q1362152", "Q2387083", "Q719413", "Q92838",
    "Q93010", "Q26703063", "Q18618629", "Q3299582", "Q56200", "Q92958", "Q13520818",
]
QUERY = """
SELECT ?p ?pLabel ?gh ?birth (GROUP_CONCAT(DISTINCT ?resLabel; separator="|") AS ?res) WHERE {
  VALUES ?p { %s }
  ?p wdt:P2037 ?gh; wdt:P569 ?birth.
  OPTIONAL { ?p wdt:P551 ?r. ?r rdfs:label ?resLabel. FILTER(LANG(?resLabel) = "en") }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
} GROUP BY ?p ?pLabel ?gh ?birth
"""


def build(rows: list[dict], today: date) -> list[dict]:
    by_person: dict[str, dict] = {}
    for row in rows:
        qid = row["p"]["value"].rsplit("/", 1)[1]
        case = by_person.setdefault(qid, {
            "id": row["gh"]["value"].lower(),
            "name": row["pLabel"]["value"],
            "birth": int(row["birth"]["value"][:4]),
            "places": sorted(p for p in row.get("res", {}).get("value", "").split("|") if p),
            "expect": [],
            "source": f"https://www.wikidata.org/wiki/{qid}",
            "kind": "public",
        })
        url = f"https://github.com/{row['gh']['value']}"
        if url not in case["expect"]:
            case["expect"].append(url)
    cases = []
    for case in by_person.values():
        if case["name"].startswith("Q"):
            continue                                # no English label
        age = today.year - case.pop("birth")
        places = case.pop("places")
        # one known residence becomes part of the text; several (old and new) are ambiguous
        text = f"{case.pop('name')}, {age} years old" + (f", from {places[0]}" if len(places) == 1 else "")
        cases.append({"id": case["id"], "text": text, **case})
    return sorted(cases, key=lambda c: c["id"])


def main() -> None:
    query = QUERY % " ".join(f"wd:{q}" for q in QIDS)
    response = httpx.get(ENDPOINT, params={"query": query}, timeout=60,
                         headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT})
    response.raise_for_status()
    for case in build(response.json()["results"]["bindings"], date.today()):
        sys.stdout.write(json.dumps(case, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
