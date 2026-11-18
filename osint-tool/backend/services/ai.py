"""Local AI layer (Ollama on this machine) with guard rails.

Rules (ROADMAP Faza 5, researcher report):
- one narrow task per call, answer forced into a JSON schema;
- the model only sees numbered evidence snippets and must cite them
  (`evidence_ids`); claims citing nothing that exists are dropped;
- every e-mail, phone number and URL the model writes must appear verbatim in
  the evidence it cites, otherwise it is removed (no invented contacts);
- the model's opinion is a weak signal: it never merges identities or changes
  the linkage score, a human makes the final call;
- if Ollama is unreachable everything works without AI.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time

import httpx

OLLAMA = os.environ.get("OLLAMA_BACKEND_URL", "").strip().rstrip("/")
FAST_MODEL = os.environ.get("OLLAMA_FAST_MODEL", "qwen2.5:7b")
SMART_MODEL = os.environ.get("OLLAMA_SMART_MODEL", "qwen3:8b")
VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "qwen2.5vl:7b")
CALL_TIMEOUT = httpx.Timeout(120.0, connect=5.0)
AVAILABILITY_TTL = 60

_gpu = asyncio.Semaphore(1)          # one model call at a time on a single GPU
_available_cache: tuple[float, bool] = (0.0, False)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s()\-]{7,}\d")


class AIUnavailable(Exception):
    pass


async def available() -> bool:
    """Is the local model server reachable? (cached for a minute)"""
    global _available_cache
    checked_at, ok = _available_cache
    if time.monotonic() - checked_at < AVAILABILITY_TTL:
        return ok
    ok = False
    if OLLAMA:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
                ok = (await client.get(f"{OLLAMA}/api/tags")).status_code == 200
        except httpx.HTTPError:
            ok = False
    _available_cache = (time.monotonic(), ok)
    return ok


async def chat_json(prompt: str, schema: dict, model: str | None = None,
                    images: list[str] | None = None) -> dict:
    """One schema-constrained call. Raises AIUnavailable on any failure."""
    if not await available():
        raise AIUnavailable("local AI is not reachable")
    message = {"role": "user", "content": prompt}
    if images:
        message["images"] = images
    body = {"model": model or FAST_MODEL, "messages": [message], "stream": False,
            "format": schema, "think": False, "keep_alive": "5m",
            "options": {"temperature": 0.1}}
    async with _gpu:
        try:
            async with httpx.AsyncClient(timeout=CALL_TIMEOUT) as client:
                response = await client.post(f"{OLLAMA}/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise AIUnavailable(f"model call failed: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise AIUnavailable(f"model returned HTTP {response.status_code}")
    try:
        return json.loads(response.json()["message"]["content"])
    except (KeyError, ValueError, TypeError) as exc:
        raise AIUnavailable("model answer was not valid JSON") from exc


# ---------------- evidence protocol ----------------

def number_evidence(snippets: list[str], prefix: str = "E") -> list[dict]:
    return [{"id": f"{prefix}{i + 1}", "text": " ".join(str(s).split())[:500]}
            for i, s in enumerate(snippets) if str(s).strip()]


def evidence_block(evidence: list[dict]) -> str:
    return "\n".join(f"[{e['id']}] {e['text']}" for e in evidence)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).lower()


def _digits(text: str) -> str:
    return re.sub(r"\D", "", str(text or ""))


def unsupported_contacts(text: str, cited: list[dict]) -> list[str]:
    """E-mails, URLs and phone numbers in `text` that no cited snippet contains."""
    haystack = _norm(" ".join(e["text"] for e in cited))
    digits = _digits(haystack)
    bad = []
    for email in _EMAIL_RE.findall(text or ""):
        if email.lower() not in haystack:
            bad.append(email)
    for url in _URL_RE.findall(text or ""):
        if url.lower().rstrip("/.,)") not in haystack:
            bad.append(url)
    for phone in _PHONE_RE.findall(text or ""):
        if len(_digits(phone)) >= 9 and _digits(phone) not in digits:
            bad.append(phone.strip())
    return bad


def check_claim(claim: dict, evidence: list[dict], text_fields: tuple[str, ...]) -> dict | None:
    """Keep a claim only if it cites real evidence and invents no contact."""
    by_id = {e["id"]: e for e in evidence}
    cited = [by_id[i] for i in claim.get("evidence_ids") or [] if i in by_id]
    if not cited:
        return None
    cleaned = dict(claim)
    cleaned["evidence_ids"] = [e["id"] for e in cited]
    for field in text_fields:
        value = str(cleaned.get(field) or "")
        for bad in unsupported_contacts(value, cited):
            value = value.replace(bad, "[removed: not in the evidence]")
        cleaned[field] = value
    return cleaned


# ---------------- task: is this candidate the same person? ----------------

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["same", "different", "unclear"]},
        "reason": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "reason", "evidence_ids"],
}


def facts_of(node: dict, limit: int = 6) -> list[str]:
    """Short, quotable facts from a node's own results (no search snippets)."""
    facts = [f"{node.get('type')} searched: {node.get('query')}"]
    for item in node.get("results") or []:
        if item.get("source") in ("web_search", "run_summary", "dns_contact"):
            continue
        text = " ".join(str(x) for x in (item.get("platform"), item.get("title"), item.get("info")) if x)
        if text:
            facts.append(text[:300])
        if len(facts) > limit:
            break
    return facts


async def review_candidate(seed: dict, candidate: dict, linkage_reason: str) -> dict:
    """Weak second opinion on a namesake candidate. Never merges anything."""
    evidence = number_evidence(facts_of(seed), "S") + number_evidence(facts_of(candidate), "C")
    prompt = (
        "Two sets of public records follow. S* describe the person being investigated, C* an "
        "account that a linkage engine did NOT merge because the evidence was weak "
        f"({linkage_reason}).\n{evidence_block(evidence)}\n\n"
        "Is C the same person as S? Answer 'same' only if specific facts agree (same rare "
        "handle, same employer, same city AND matching details), 'different' if facts conflict "
        "(different country, age, profession), otherwise 'unclear'. A shared common name alone "
        "is 'unclear'. Cite the evidence ids you used. Do not invent facts."
    )
    answer = await chat_json(prompt, REVIEW_SCHEMA)
    claim = check_claim(answer, evidence, ("reason",))
    if claim is None:
        return {"verdict": "unclear", "reason": "the model cited no evidence", "evidence_ids": [],
                "model": FAST_MODEL, "weak_signal": True}
    verdict = claim.get("verdict") if claim.get("verdict") in ("same", "different", "unclear") else "unclear"
    return {"verdict": verdict, "reason": claim["reason"][:300], "evidence_ids": claim["evidence_ids"],
            "model": FAST_MODEL, "weak_signal": True}


async def review_clusters(nodes: list[dict], clusters: list[dict], max_reviews: int = 4,
                          budget_seconds: float = 60.0) -> int:
    """Attach `ai_review` to the first few unmerged candidates, in place."""
    if not await available():
        return 0
    by_key = {n.get("key"): n for n in nodes}
    started, done = time.monotonic(), 0
    for cluster in clusters:
        seed = by_key.get((cluster.get("members") or [None])[0])
        for cand in cluster.get("candidates") or []:
            if done >= max_reviews or time.monotonic() - started > budget_seconds:
                return done
            other = by_key.get(cand.get("key"))
            if seed is None or other is None:
                continue
            try:
                cand["ai_review"] = await review_candidate(seed, other, cand.get("reason", ""))
                done += 1
            except AIUnavailable:
                return done
    return done
