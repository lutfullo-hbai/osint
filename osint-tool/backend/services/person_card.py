"""Person card (ROADMAP 7.1): one Agent candidate as a page and a PDF.

What it holds is exactly what the candidate already has: the profile fields
with the pages they came from, the contacts the person published themselves
(7.2), and the evidence chain from what you searched to each record. Nothing
new is looked up here, and the card says whether you confirmed or rejected
the candidate.
"""
from __future__ import annotations

from datetime import datetime, timezone

from services.dossier import (
    _AMBER,
    _GREEN,
    _MUTED,
    _Dossier,
    _INK,
    _VIOLET,
    FONT,
    _badge,
    _kv,
    _register_fonts,
    _safe,
    _section,
)

FIELD_LABELS = {
    "name": "Name",
    "birth_year": "Birth year",
    "location": "Location",
    "work": "Work / study",
    "emails": "E-mail",
    "usernames": "Usernames",
    "profiles": "Profiles",
}
CONTACT_LABELS = {"email": "E-mail", "phone": "Phone", "messenger": "Messenger",
                  "social": "Social profile", "website": "Website"}
LEVEL_COLOR = {"strong": _GREEN, "possible": _AMBER, "weak": _MUTED}
NOTICE = ("A lead assembled from public sources, not an identification. Every value lists where it "
          "was seen; check those pages before relying on it. Contacts are only those the person "
          "published; none were guessed.")


class CardError(LookupError):
    pass


class _Card(_Dossier):
    heading = "NEXUS  /  PERSON CARD"


def build_card(run: dict, candidate_id: str) -> dict:
    result = run.get("result") or {}
    candidate = next((c for c in result.get("candidates") or [] if c.get("id") == candidate_id), None)
    if candidate is None:
        raise CardError("Candidate not found in this run.")
    decision = (run.get("decisions") or {}).get(candidate_id) or {}
    return {
        "run_id": run.get("id"),
        "query": result.get("query") or run.get("text"),
        "parsed": result.get("parsed") or run.get("parsed") or {},
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "decision": decision.get("decision"),
        "decision_note": decision.get("note") or "",
        "notice": NOTICE,
        "candidate": {k: candidate.get(k) for k in
                      ("id", "label", "level", "score", "fields", "missing", "contacts", "chain",
                       "why", "contradictions", "members", "ai_review")},
    }


def _sources_text(sources: list) -> str:
    out = []
    for src in sources or []:
        if isinstance(src, dict):
            out.append(f"{src.get('platform') or 'source'}" + (f" <{src['url']}>" if src.get("url") else "")
                       + (f" ({str(src['retrieved_at'])[:16].replace('T', ' ')} UTC)" if src.get("retrieved_at") else ""))
        else:
            out.append(str(src))
    return "; ".join(out)


def card_pdf(card: dict) -> bytes:
    c = card["candidate"]
    pdf = _Card()
    _register_fonts(pdf)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(10, 22, 10)
    pdf.add_page()

    pdf.set_font(FONT, "B", 20)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 12, _safe(c.get("label") or "Candidate"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT, "", 10)
    pdf.set_text_color(*_MUTED)
    pdf.multi_cell(0, 6, _safe(f"Person card — request: {card.get('query') or ''}"),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    _badge(pdf, f"{c.get('level')} lead · score {c.get('score')}", LEVEL_COLOR.get(c.get("level"), _MUTED))
    pdf.set_x(pdf.get_x() + 3)
    decision = card.get("decision")
    _badge(pdf, {"confirmed": "confirmed by you", "rejected": "rejected by you"}.get(decision, "not decided yet"),
           {"confirmed": _GREEN, "rejected": _AMBER}.get(decision, _VIOLET))
    pdf.ln(8)
    if card.get("decision_note"):
        _kv(pdf, "Your note", card["decision_note"])
    _kv(pdf, "Generated", card.get("generated_at") or "")

    _section(pdf, "Profile")
    fields = c.get("fields") or {}
    for key, label in FIELD_LABELS.items():
        values = fields.get(key) or []
        if not values:
            _kv(pdf, label, "not found")
            continue
        if key == "profiles":
            for v in values:
                _kv(pdf, label, _sources_text(v.get("sources")))
                label = ""
            continue
        for v in values:
            _kv(pdf, label, f"{v.get('value')}   — seen on: {_sources_text(v.get('sources'))}")
            label = ""

    _section(pdf, "Published contacts")
    contacts = c.get("contacts") or []
    if not contacts:
        _kv(pdf, "", "None published on the pages that were read.")
    for item in contacts:
        _kv(pdf, CONTACT_LABELS.get(item.get("kind"), item.get("kind") or ""),
            f"{item.get('value')}   — {item.get('how') or ''}; page: {'; '.join(item.get('sources') or [])}")

    _section(pdf, "Evidence chain")
    for link in c.get("chain") or []:
        steps = " → ".join(f"{s.get('type')} '{s.get('value')}' ({s.get('via')})" for s in link.get("path") or [])
        _kv(pdf, "", steps or link.get("record") or "")
    if c.get("why"):
        _kv(pdf, "Why linked", "; ".join(c["why"]))
    if c.get("contradictions"):
        pdf.set_text_color(*_AMBER)
        _kv(pdf, "Contradicts", "; ".join(c["contradictions"]))
        pdf.set_text_color(*_INK)
    if c.get("missing"):
        _kv(pdf, "Not found", ", ".join(FIELD_LABELS.get(m, m) for m in c["missing"]))
    review = c.get("ai_review") or {}
    if review:
        _kv(pdf, "AI (weak signal)", f"{review.get('verdict')} — {review.get('reason')}")

    pdf.ln(4)
    pdf.set_font(FONT, "I", 8)
    pdf.set_text_color(*_MUTED)
    pdf.multi_cell(0, 4.5, _safe(card.get("notice") or NOTICE), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
