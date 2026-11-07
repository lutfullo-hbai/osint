import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import main
from security import limiter


@pytest.fixture(autouse=True)
def reset_limiter():
    limiter.reset()
    yield
    limiter.reset()


def make_client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=main.app),
        base_url="http://testserver",
    )


async def test_health_is_open_and_has_request_id(monkeypatch):
    monkeypatch.setenv("OSINT_API_KEY", "secret-key")
    async with make_client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers.get("X-Request-ID")


async def test_api_requires_key_when_configured(monkeypatch):
    monkeypatch.setenv("OSINT_API_KEY", "secret-key")
    async with make_client() as client:
        missing = await client.get("/api/catalog")
        wrong = await client.get("/api/catalog", headers={"X-API-Key": "nope"})
        valid = await client.get(
            "/api/catalog", headers={"X-API-Key": "secret-key"}
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert valid.status_code == 200
    assert valid.json()["status"] == "success"


async def test_api_is_open_when_key_not_configured(monkeypatch):
    monkeypatch.delenv("OSINT_API_KEY", raising=False)
    async with make_client() as client:
        response = await client.get("/api/catalog")

    assert response.status_code == 200


async def test_catalog_is_rate_limited(monkeypatch):
    monkeypatch.delenv("OSINT_API_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT_GENERAL", "1/minute")
    async with make_client() as client:
        first = await client.get("/api/catalog")
        second = await client.get("/api/catalog")

    assert first.status_code == 200
    assert second.status_code == 429
    assert "Retry-After" in second.headers


async def test_audit_log_hashes_query_without_raw_value(monkeypatch, caplog):
    monkeypatch.delenv("OSINT_API_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT_LIGHT", "100/minute")
    monkeypatch.setattr(main.audit_logger, "propagate", True)
    caplog.set_level("INFO", logger="osint.audit")
    raw_query = "!!!@@@"

    async with make_client() as client:
        response = await client.post("/api/name", json={"query": raw_query})

    assert response.status_code == 400
    messages = [record.getMessage() for record in caplog.records]
    audit_messages = [m for m in messages if '"event": "audit"' in m]
    assert audit_messages
    assert all(raw_query not in message for message in audit_messages)
    assert any('"query_hash": "sha256:' in message for message in audit_messages)
