import httpx
import pytest

from tools.net_guard import UnsafeURLError, ensure_safe_url, safe_get

PUBLIC_IP = "93.184.216.34"


def _fake_resolver(host: str, port: int) -> set[str]:
    if host in {"example.com", "example.org"}:
        return {PUBLIC_IP}
    return {host}


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "gopher://example.com/",
        "http://user:pass@example.com/",
        "http://127.0.0.1/",
        "http://localhost/",
        "http://localhost.localdomain/",
        "http://service.internal/",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[fd00::1]/",
        "http://example.com:8080/",
        "http://example.com:22/",
        "http:///no-host",
    ],
)
async def test_rejects_unsafe_urls(monkeypatch, url):
    monkeypatch.setattr("tools.net_guard._resolve_sync", _fake_resolver)
    with pytest.raises(UnsafeURLError):
        await ensure_safe_url(url)


async def test_allows_public_https_url(monkeypatch):
    monkeypatch.setattr("tools.net_guard._resolve_sync", _fake_resolver)
    assert await ensure_safe_url("https://example.com/page?q=1") == (
        "https://example.com/page?q=1"
    )


async def test_safe_get_follows_public_redirect(monkeypatch):
    monkeypatch.setattr("tools.net_guard._resolve_sync", _fake_resolver)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "https://example.org/ok"})
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        response = await safe_get(client, "https://example.com/start")

    assert response.status_code == 200
    assert str(response.url) == "https://example.org/ok"


async def test_safe_get_blocks_redirect_to_private(monkeypatch):
    monkeypatch.setattr("tools.net_guard._resolve_sync", _fake_resolver)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(UnsafeURLError):
            await safe_get(client, "https://example.com/start")
