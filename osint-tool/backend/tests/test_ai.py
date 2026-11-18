"""Faza 5: local AI layer — evidence citing, no invented contacts, weak signal only."""
import pytest

from services import ai
from services import geolocate as geo

EVIDENCE = ai.number_evidence([
    "GitHub profile: Name: Jane Roe; Location: Tashkent; Email: jane.roe@mail.uz",
    "Telegram channel bio: call +998 90 123 45 67, site https://janeroe.uz",
])


def test_contacts_must_be_in_cited_evidence():
    cited = [EVIDENCE[0]]
    assert ai.unsupported_contacts("write to jane.roe@mail.uz", cited) == []
    assert ai.unsupported_contacts("write to jane@gmail.com", cited) == ["jane@gmail.com"]
    assert ai.unsupported_contacts("phone +998 90 123 45 67", [EVIDENCE[1]]) == []
    assert ai.unsupported_contacts("phone +998 91 000 00 00", [EVIDENCE[1]]) == ["+998 91 000 00 00"]
    assert ai.unsupported_contacts("see https://evil.example", [EVIDENCE[1]]) == ["https://evil.example"]


def test_check_claim_drops_uncited_and_redacts_invented():
    assert ai.check_claim({"reason": "x", "evidence_ids": ["E9"]}, EVIDENCE, ("reason",)) is None
    claim = ai.check_claim({"reason": "uses jane.roe@mail.uz and jroe@yahoo.com",
                            "evidence_ids": ["E1", "E7"]}, EVIDENCE, ("reason",))
    assert claim["evidence_ids"] == ["E1"]
    assert "jane.roe@mail.uz" in claim["reason"] and "jroe@yahoo.com" not in claim["reason"]
    assert "[removed: not in the evidence]" in claim["reason"]


@pytest.mark.asyncio
async def test_review_candidate_is_cited_and_weak(monkeypatch):
    async def fake_chat(prompt, schema, model=None, images=None):
        assert "[S1]" in prompt and "[C1]" in prompt
        return {"verdict": "different", "reason": "S lives in Tashkent, C in Lisbon; contact x@y.com",
                "evidence_ids": ["S2", "C2"]}
    monkeypatch.setattr(ai, "chat_json", fake_chat)
    seed = {"type": "name", "query": "Jane Roe", "results": [{"platform": "GitHub", "info": "Location: Tashkent"}]}
    cand = {"type": "username", "query": "janer", "results": [{"platform": "GitLab", "info": "Location: Lisbon"}]}
    review = await ai.review_candidate(seed, cand, "display name matches")
    assert review["verdict"] == "different" and review["weak_signal"] is True
    assert "x@y.com" not in review["reason"]


@pytest.mark.asyncio
async def test_review_clusters_annotates_but_never_merges(monkeypatch):
    async def yes():
        return True

    async def fake_review(seed, cand, reason):
        return {"verdict": "same", "reason": "r", "evidence_ids": ["S1"], "model": "m", "weak_signal": True}
    monkeypatch.setattr(ai, "available", yes)
    monkeypatch.setattr(ai, "review_candidate", fake_review)
    nodes = [{"key": "name:a", "type": "name", "query": "A B", "results": []},
             {"key": "username:ab", "type": "username", "query": "ab", "results": []}]
    clusters = [{"members": ["name:a"], "candidates": [{"key": "username:ab", "query": "ab", "reason": "x"}]},
                {"members": ["username:ab"], "candidates": []}]
    assert await ai.review_clusters(nodes, clusters) == 1
    assert clusters[0]["candidates"][0]["ai_review"]["verdict"] == "same"
    assert clusters[0]["members"] == ["name:a"]          # still not merged


@pytest.mark.asyncio
async def test_everything_works_without_ai(monkeypatch):
    monkeypatch.setattr(ai, "OLLAMA", "")
    monkeypatch.setattr(ai, "_available_cache", (0.0, False))
    assert await ai.available() is False
    with pytest.raises(ai.AIUnavailable):
        await ai.chat_json("x", {"type": "object"})
    assert await geo.server_vision({"preview_b64": "abc"}) is None


@pytest.mark.asyncio
async def test_server_vision_refines_places(monkeypatch):
    async def yes():
        return True

    async def fake_chat(prompt, schema, model=None, images=None):
        assert images == ["abc"] and model == ai.VISION_MODEL
        return {"clues": [{"clue": "Uzbek Latin signs", "points_to": "Uzbekistan"}],
                "places": [{"name": "Registan", "kind": "landmark", "confidence": 0.9, "evidence": "domes"}],
                "country_codes": ["uz"]}

    async def fake_refine(raw, places, codes):
        assert places[0]["name"] == "Registan" and codes == ["UZ"]
        return {"candidates": [{"lat": 39.65, "lon": 66.97}], "warnings": []}
    monkeypatch.setattr(ai, "available", yes)
    monkeypatch.setattr(ai, "chat_json", fake_chat)
    monkeypatch.setattr(geo, "refine", fake_refine)
    out = await geo.server_vision({"preview_b64": "abc", "ocr_text": "", "text_hints": [], "raw_candidates": []})
    assert out["candidates"][0]["lat"] == 39.65 and out["clues"][0]["points_to"] == "Uzbekistan"
