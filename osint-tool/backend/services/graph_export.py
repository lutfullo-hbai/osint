"""Deep Scan graph export (ROADMAP 7.8): GraphML (Gephi, yEd, Cytoscape) and
a CSV that Maltego CE's "Import Graph from Table" reads.

Each searched record becomes a node; each pivot an edge labelled with how it
was found. The pages that produced a record go along as evidence: in GraphML
as an attribute and as URL nodes, in the CSV as rows linking the record to the
page. Nothing is added that the scan did not see.
"""
from __future__ import annotations

import csv
import io
import re
from xml.sax.saxutils import escape, quoteattr

MAX_EVIDENCE_PER_NODE = 8

MALTEGO_TYPES = {
    "name": "maltego.Person",
    "username": "maltego.Alias",
    "email": "maltego.EmailAddress",
    "phone": "maltego.PhoneNumber",
    "domain": "maltego.Domain",
    "host": "maltego.Domain",
    "ip": "maltego.IPv4Address",
    "company": "maltego.Company",
    "url": "maltego.URL",
}

_VIA_LABEL = {
    "knowledge_base": "listed on a knowledge base",
    "age_confirmed": "this name at the age you gave",
    "profile_link": "linked from a profile",
    "name_match": "same display name",
    "name_variant": "username guessed from the name",
    "email_localpart": "e-mail name used as a handle",
    "official_register": "official register",
    "stated": "given by you",
    None: "pivot",
}


def _normalise(scan) -> dict:
    """The POSTed scan comes from the browser: keep only well-formed nodes
    (dicts with a key), edges and clusters, so junk gives a 200, never a 500."""
    scan = scan if isinstance(scan, dict) else {}
    as_list = lambda v: v if isinstance(v, list) else []  # noqa: E731
    nodes, seen = [], set()
    for node in as_list(scan.get("nodes")):
        if isinstance(node, dict) and node.get("key") not in (None, "") and str(node["key"]) not in seen:
            seen.add(str(node["key"]))
            via = node.get("via")
            nodes.append({**node, "key": str(node["key"]),
                          "via": via if via is None or isinstance(via, str) else str(via)})
    return {
        "query": str(scan.get("query") or ""),
        "nodes": nodes,
        "edges": [e for e in as_list(scan.get("edges"))
                  if isinstance(e, dict) and isinstance(e.get("from"), str) and isinstance(e.get("to"), str)],
        "clusters": [c for c in as_list(scan.get("clusters")) if isinstance(c, dict)],
    }


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _evidence(node: dict) -> list[dict]:
    out = []
    results = node.get("results")
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if not url.startswith(("http://", "https://")):
            continue
        out.append({"platform": str(item.get("platform") or "")[:80], "url": url,
                    "info": " ".join(str(item.get("info") or "").split())[:300]})
        if len(out) >= MAX_EVIDENCE_PER_NODE:
            break
    return out


def _cluster_of(scan: dict) -> dict[str, str]:
    return {key: str(i) for i, cl in enumerate(scan.get("clusters") or [])
            for key in (cl.get("members") if isinstance(cl.get("members"), list) else [])
            if isinstance(key, str)}


def _clean(text) -> str:
    # XML 1.0 forbids most control characters
    return "".join(ch for ch in str(text or "") if ch in "\t\n\r" or ord(ch) >= 32)


def to_graphml(scan: dict) -> str:
    scan = _normalise(scan)
    nodes = scan["nodes"]
    keys = {n.get("key") for n in nodes}
    cluster = _cluster_of(scan)
    attrs = [("type", "node"), ("value", "node"), ("depth", "node"), ("via", "node"),
             ("results", "node"), ("cluster", "node"), ("not_followed", "node"),
             ("evidence", "node"), ("url", "node"), ("label", "edge")]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">']
    for name, scope in attrs:
        kind = "int" if name in ("depth", "results") else "string"
        out.append(f'  <key id="{name}" for="{scope}" attr.name="{name}" attr.type="{kind}"/>')
    out.append(f'  <graph id={quoteattr(_clean(scan.get("query") or "deep-scan"))} edgedefault="directed">')

    def data(name: str, value) -> str:
        return f'<data key="{name}">{escape(_clean(value))}</data>'

    url_nodes: dict[str, str] = {}
    evidence_edges = []
    for node in nodes:
        evidence = _evidence(node)
        fields = [data("type", node.get("type")), data("value", node.get("query")),
                  data("depth", _int(node.get("depth"))), data("via", _VIA_LABEL.get(node.get("via"), node.get("via"))),
                  data("results", _int(node.get("count")))]
        if node.get("key") in cluster:
            fields.append(data("cluster", cluster[node["key"]]))
        if node.get("not_followed"):
            fields.append(data("not_followed", node["not_followed"]))
        if evidence:
            fields.append(data("evidence", "\n".join(f"{e['platform']}: {e['url']}" for e in evidence)))
        out.append(f'    <node id={quoteattr(_clean(node.get("key")))}>{"".join(fields)}</node>')
        for e in evidence:
            uid = url_nodes.setdefault(e["url"], f"url:{len(url_nodes)}")
            evidence_edges.append((node["key"], uid, e["platform"] or "seen on"))
    for url, uid in url_nodes.items():
        out.append(f'    <node id="{uid}">{data("type", "url")}{data("value", url)}{data("url", url)}</node>')
    by_key = {n.get("key"): n for n in nodes}
    for i, edge in enumerate(scan["edges"]):
        src, dst = edge.get("from"), edge.get("to")
        if src in keys and dst in keys:
            via = (by_key.get(dst) or {}).get("via")
            out.append(f'    <edge id="e{i}" source={quoteattr(_clean(src))} target={quoteattr(_clean(dst))}>'
                       f'{data("label", _VIA_LABEL.get(via, via))}</edge>')
    for j, (src, dst, label) in enumerate(evidence_edges):
        out.append(f'    <edge id="v{j}" source={quoteattr(_clean(src))} target="{dst}">{data("label", label)}</edge>')
    out += ["  </graph>", "</graphml>", ""]
    return "\n".join(out)


MALTEGO_COLUMNS = ["source_entity_type", "source_value", "target_entity_type", "target_value",
                   "link_label", "evidence_url"]


def _cell(value) -> str:
    """Neutralise spreadsheet formulas (CSV injection) without breaking phone
    numbers: "=HYPERLINK(...)" -> "'=HYPERLINK(...)", "+998901234567" stays."""
    text = _clean(value).replace("\r", " ").replace("\n", " ")
    if text[:1] in ("=", "@", "\t") or (text[:1] in ("+", "-") and not re.fullmatch(r"[+\-][\d\s()\-]+", text)):
        return "'" + text
    return text


def to_maltego_csv(scan: dict) -> str:
    """One row per link. In Maltego CE: Import → Import Graph from Table, then
    map source_* and target_* columns to the entity types they name."""
    scan = _normalise(scan)
    nodes = scan["nodes"]
    by_key = {n.get("key"): n for n in nodes}
    buf = io.StringIO()
    raw_writer = csv.writer(buf)

    class _Safe:
        @staticmethod
        def writerow(row):
            raw_writer.writerow([_cell(v) for v in row])
    writer = _Safe()
    writer.writerow(MALTEGO_COLUMNS)

    def entity(node: dict) -> tuple[str, str]:
        return MALTEGO_TYPES.get(node.get("type"), "maltego.Phrase"), str(node.get("query") or "")

    linked = set()
    for edge in scan["edges"]:
        src, dst = by_key.get(edge.get("from")), by_key.get(edge.get("to"))
        if not src or not dst:
            continue
        evidence = _evidence(src)
        writer.writerow([*entity(src), *entity(dst), _VIA_LABEL.get(dst.get("via"), dst.get("via")),
                         evidence[0]["url"] if evidence else ""])
        linked.update((src["key"], dst["key"]))
    for node in nodes:
        for e in _evidence(node):
            writer.writerow([*entity(node), MALTEGO_TYPES["url"], e["url"], e["platform"] or "seen on", e["url"]])
        if node["key"] not in linked and not _evidence(node):
            writer.writerow([*entity(node), "", "", "", ""])
    return buf.getvalue()
