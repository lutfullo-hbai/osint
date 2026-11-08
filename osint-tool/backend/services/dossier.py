"""PDF dossier — a printable investigation report from a scan or a case.

Takes a correlated result (Deep Scan output, a single-category search, or a
stored case) and renders a structured PDF: cover, confidence summary, identity
clusters with their evidence, an entity graph, and the findings grouped by
source. Server-side with fpdf2 — pure Python, no system libraries, so the
Docker image stays slim and the output is identical everywhere.

Every page carries the "leads, not proof" disclaimer. This report organizes
data we already gathered; it reaches no new source.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fpdf import FPDF

from services.correlate import correlate

# palette (RGB) echoing the NEXUS theme, muted for print legibility
_INK = (24, 24, 34)
_MUTED = (110, 116, 140)
_VIOLET = (120, 70, 190)
_CYAN = (20, 130, 150)
_AMBER = (170, 120, 10)
_GREEN = (30, 140, 90)
_LINE = (210, 212, 224)

_CONF_COLOR = {
    "high": _GREEN,
    "medium": _AMBER,
    "low": _MUTED,
    "single": _MUTED,
}


def _safe(text) -> str:
    """fpdf2's core fonts are latin-1; scraped data can hold anything.

    Replace unencodable characters rather than crash the whole report.
    """
    return str(text).encode("latin-1", "replace").decode("latin-1")


class _Dossier(FPDF):
    def header(self):
        self.set_fill_color(*_VIOLET)
        self.rect(0, 0, self.w, 16, style="F")
        self.set_xy(10, 4)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 13)
        self.cell(0, 8, "NEXUS  /  OSINT DOSSIER", align="L")
        self.set_font("Helvetica", "", 8)
        self.set_xy(10, 4)
        self.cell(
            self.w - 20, 8,
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            align="R",
        )
        self.set_y(22)
        self.set_text_color(*_INK)

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(*_LINE)
        self.line(10, self.get_y(), self.w - 10, self.get_y())
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*_MUTED)
        self.cell(
            0, 6,
            "Open-source leads, not proof. A shared handle or name can belong "
            "to different people. Verify independently.",
            align="L",
        )
        self.set_text_color(*_INK)
        self.set_font("Helvetica", "", 7)
        self.cell(0, 6, f"Page {self.page_no()}", align="R")


def _section(pdf: _Dossier, title: str) -> None:
    if pdf.get_y() > pdf.h - 40:
        pdf.add_page()
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*_VIOLET)
    pdf.cell(0, 8, _safe(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*_LINE)
    pdf.line(10, pdf.get_y(), pdf.w - 10, pdf.get_y())
    pdf.ln(2)
    pdf.set_text_color(*_INK)


def _kv(pdf: _Dossier, label: str, value: str) -> None:
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*_MUTED)
    pdf.cell(32, 5.5, _safe(label))
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_INK)
    pdf.multi_cell(0, 5.5, _safe(value), new_x="LMARGIN", new_y="NEXT")


def _badge(pdf: _Dossier, text: str, color) -> None:
    pdf.set_font("Helvetica", "B", 8)
    w = pdf.get_string_width(_safe(text)) + 6
    x, y = pdf.get_x(), pdf.get_y()
    pdf.set_fill_color(*color)
    pdf.set_text_color(255, 255, 255)
    pdf.rect(x, y, w, 5, style="F")
    pdf.cell(w, 5, _safe(text), align="C")
    pdf.set_text_color(*_INK)


def _draw_graph(pdf: _Dossier, nodes: list[dict], edges: list[dict]) -> None:
    """Layered node/edge diagram by depth, drawn with primitives."""
    positioned = [n for n in nodes if "depth" in n]
    if len(positioned) < 2:
        return
    _section(pdf, "Entity graph")

    by_depth: dict[int, list[dict]] = {}
    for n in positioned:
        by_depth.setdefault(n.get("depth", 0), []).append(n)
    depths = sorted(by_depth)

    left, top = 14.0, pdf.get_y() + 4
    usable_w = pdf.w - 28
    col_w = usable_w / max(len(depths), 1)
    row_h = 9.0
    max_rows = max(len(by_depth[d]) for d in depths)
    height = max_rows * row_h + 6

    pos: dict[str, tuple[float, float]] = {}
    for di, d in enumerate(depths):
        col = by_depth[d]
        col_top = top + (height - len(col) * row_h) / 2
        for ni, node in enumerate(col):
            x = left + di * col_w + 4
            y = col_top + ni * row_h + row_h / 2
            pos[node.get("key")] = (x, y)

    pdf.set_draw_color(*_LINE)
    for e in edges:
        a, b = pos.get(e.get("from")), pos.get(e.get("to"))
        if a and b:
            pdf.line(a[0] + 2, a[1], b[0] - 1, b[1])

    for node in positioned:
        key = node.get("key")
        if key not in pos:
            continue
        x, y = pos[key]
        color = _CYAN if node.get("type") in ("domain", "ip") else _VIOLET
        pdf.set_fill_color(*color)
        pdf.ellipse(x - 1.4, y - 1.4, 2.8, 2.8, style="F")
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*_INK)
        label = f"{node.get('type')}: {node.get('query')}"
        pdf.text(x + 3, y + 1, _safe(label[:34]))

    pdf.set_y(top + height + 2)


def _normalize(data: dict) -> dict:
    """Coerce any result shape into {title, subtitle, nodes, edges, clusters}."""
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        # a plain single-category search -> one node holding its results
        nodes = [{
            "key": f"{data.get('category', 'result')}:{data.get('query', '')}",
            "type": data.get("category", "result"),
            "query": data.get("query", ""),
            "results": data.get("results", []),
        }]
    edges = data.get("edges", []) if isinstance(data.get("edges"), list) else []

    clusters = data.get("clusters")
    if not isinstance(clusters, list):
        clusters = correlate(nodes)["clusters"]

    seed = data.get("query", "investigation")
    stype = data.get("seed_type") or data.get("category") or "scan"
    return {
        "title": _safe(data.get("case_name") or seed),
        "subtitle": _safe(f"seed type: {stype}"),
        "seed": _safe(seed),
        "seed_type": _safe(stype),
        "nodes": nodes,
        "edges": edges,
        "clusters": clusters,
        "warnings": data.get("warnings", []),
    }


def build_dossier(data: dict) -> bytes:
    report = _normalize(data)
    pdf = _Dossier()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(10, 22, 10)
    pdf.add_page()

    # cover block
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 12, report["title"], new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_MUTED)
    pdf.cell(0, 6, report["subtitle"], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    nodes = report["nodes"]
    clusters = report["clusters"]
    multi = [c for c in clusters if len(c.get("members", [])) > 1]
    total_findings = sum(len(n.get("results", [])) for n in nodes)

    _kv(pdf, "Seed", report["seed"])
    _kv(pdf, "Nodes", str(len(nodes)))
    _kv(pdf, "Findings", str(total_findings))
    _kv(pdf, "Identity clusters", str(len(multi)))
    best = max((c.get("confidence") for c in multi), default="n/a",
               key=lambda c: {"high": 3, "medium": 2, "low": 1}.get(c, 0))
    _kv(pdf, "Top confidence", best)

    # identity clusters
    if multi:
        _section(pdf, f"Identity clusters ({len(multi)})")
        for c in multi:
            if pdf.get_y() > pdf.h - 45:
                pdf.add_page()
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 6, _safe(c.get("label", "entity")), new_x="LMARGIN", new_y="NEXT")
            conf = c.get("confidence", "low")
            _badge(pdf, f"{conf} - {len(c.get('members', []))} nodes",
                   _CONF_COLOR.get(conf, _MUTED))
            pdf.ln(7)
            ids = c.get("identifiers", {})
            for key in ("names", "emails", "usernames", "domains"):
                vals = ids.get(key) or []
                if vals:
                    shown = vals[:12]
                    _kv(pdf, key, ", ".join(shown) +
                        (f"  (+{len(vals) - 12} more)" if len(vals) > 12 else ""))
            if c.get("signals"):
                _kv(pdf, "why linked", "; ".join(c["signals"]))
            for x in c.get("contradictions", []):
                pdf.set_text_color(*_AMBER)
                pdf.set_font("Helvetica", "I", 9)
                pdf.multi_cell(0, 5, _safe("! " + x), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(*_INK)
            if c.get("platforms"):
                plats = c["platforms"][:20]
                _kv(pdf, "seen on", ", ".join(plats) +
                    (f"  (+{len(c['platforms']) - 20} more)" if len(c["platforms"]) > 20 else ""))
            pdf.ln(2)

    # graph
    _draw_graph(pdf, nodes, report["edges"])

    # findings by node
    _section(pdf, "Findings by source")
    for node in nodes:
        results = node.get("results", []) or []
        if not results:
            continue
        if pdf.get_y() > pdf.h - 30:
            pdf.add_page()
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*_CYAN)
        header = f"{node.get('type')}: {node.get('query')}  ({len(results)})"
        pdf.cell(0, 6, _safe(header), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*_INK)
        for item in results[:40]:
            if pdf.get_y() > pdf.h - 24:
                pdf.add_page()
            title = item.get("platform") or item.get("name") or item.get("site") or "item"
            status = item.get("status", "")
            pdf.set_font("Helvetica", "B", 9)
            pdf.multi_cell(0, 5, _safe(f"- {title}" + (f"  [{status}]" if status else "")),
                           new_x="LMARGIN", new_y="NEXT")
            url = item.get("url") or item.get("profile_url")
            if url:
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(*_CYAN)
                pdf.multi_cell(0, 4.5, _safe(url), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(*_INK)
            info = item.get("info")
            if info:
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(*_MUTED)
                pdf.multi_cell(0, 4.5, _safe(str(info)[:400]), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(*_INK)
        pdf.ln(1)

    # unavailable sources
    warnings = report.get("warnings") or []
    if warnings:
        _section(pdf, f"Unavailable or skipped sources ({len(warnings)})")
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_MUTED)
        for w in warnings[:30]:
            pdf.multi_cell(0, 4.5, _safe("- " + str(w)), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*_INK)

    out = pdf.output()
    return bytes(out)
