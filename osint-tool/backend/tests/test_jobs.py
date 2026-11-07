import pytest
from httpx import ASGITransport, AsyncClient

import main
import routers.jobs as jobs
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


async def test_job_rejects_unknown_category(monkeypatch):
    monkeypatch.delenv("OSINT_API_KEY", raising=False)
    async with make_client() as client:
        response = await client.post(
            "/api/jobs", json={"category": "bogus", "query": "x"}
        )

    assert response.status_code == 400
    assert "Unknown category" in response.json()["message"]


async def test_job_rejects_empty_query(monkeypatch):
    monkeypatch.delenv("OSINT_API_KEY", raising=False)
    async with make_client() as client:
        response = await client.post(
            "/api/jobs", json={"category": "name", "query": "   "}
        )

    assert response.status_code == 400


async def test_job_queue_disabled_without_redis(monkeypatch):
    monkeypatch.delenv("OSINT_API_KEY", raising=False)
    monkeypatch.setattr(jobs, "REDIS_URL", "")
    monkeypatch.setattr(jobs, "_pool", None)

    async with make_client() as client:
        response = await client.post(
            "/api/jobs", json={"category": "name", "query": "John Doe"}
        )

    assert response.status_code == 503
    assert "disabled" in response.json()["message"].lower()
