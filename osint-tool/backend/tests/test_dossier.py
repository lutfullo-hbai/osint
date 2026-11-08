import pytest
from httpx import ASGITransport, AsyncClient

import main
from services.dossier import build_dossier


def _is_pdf(blob: bytes) -> bool:
    return isinstance(blob, (bytes, bytearray)) and blob[:5] == b"%PDF-"


def test_build_from_deep_scan_shape():
    data = {
        "query": "jane@doe.com",
        "seed_type": "email",
        "nodes": [
            {"key": "email:jane@doe.com", "type": "email", "query": "jane@doe.com",
             "depth": 0, "results": [{"platform": "Gravatar",
                                      "url": "https://gravatar.com/jane",
                                      "info": "Name: Jane Doe"}]},
            {"key": "username:jane", "type": "username", "query": "jane",
             "depth": 1, "results": []},
        ],
        "edges": [{"from": "email:jane@doe.com", "to": "username:jane"}],
        "clusters": [{
            "label": "jane@doe.com",
            "members": ["email:jane@doe.com", "username:jane"],
            "identifiers": {"usernames": ["jane"], "emails": ["jane@doe.com"],
                            "names": ["jane doe"], "domains": []},
            "platforms": ["Gravatar"],
            "confidence": "high", "score": 5,
            "signals": ["shared email jane@doe.com"], "contradictions": [],
        }],
        "warnings": ["crt.sh: HTTP 502"],
    }
    pdf = build_dossier(data)
    assert _is_pdf(pdf)
    assert len(pdf) > 1000


def test_build_from_plain_search_shape():
    # a single-category result with no nodes must still render
    data = {
        "category": "domain", "query": "example.com",
        "results": [{"platform": "DNS records", "url": "https://x", "info": "A 1.2.3.4"}],
    }
    pdf = build_dossier(data)
    assert _is_pdf(pdf)


def test_build_survives_non_latin_text():
    data = {
        "query": "测试", "seed_type": "name",
        "nodes": [{"key": "name:x", "type": "name", "query": "测试", "depth": 0,
                   "results": [{"platform": "飞机移动", "info": "名字: 测试 — ünïcödé"}]}],
    }
    pdf = build_dossier(data)  # must not raise on latin-1-incompatible chars
    assert _is_pdf(pdf)


@pytest.mark.asyncio
async def test_dossier_endpoint_returns_pdf():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/dossier", json={"data": {
            "category": "domain", "query": "example.com",
            "results": [{"platform": "DNS", "url": "https://x", "info": "A"}],
        }})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"
    assert "attachment" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_dossier_endpoint_requires_input():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/dossier", json={})
    assert resp.status_code == 400
