import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}
BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost", ".home.arpa")
MAX_REDIRECTS = 5


class UnsafeURLError(ValueError):
    pass


def _port_of(parsed) -> int | None:
    try:
        return parsed.port
    except ValueError as exc:
        raise UnsafeURLError("URL contains an invalid port.") from exc


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(ip.is_global) and not ip.is_multicast


def _resolve_sync(host: str, port: int) -> set[str]:
    try:
        infos = socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise UnsafeURLError(f"Could not resolve host '{host}'.") from exc
    return {info[4][0] for info in infos}


async def ensure_safe_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError("Only http and https URLs are allowed.")
    if parsed.username or parsed.password:
        raise UnsafeURLError("URLs with embedded credentials are not allowed.")

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise UnsafeURLError("URL has no hostname.")
    if host == "localhost" or host.endswith(BLOCKED_HOST_SUFFIXES):
        raise UnsafeURLError("Local hostnames are not allowed.")

    port = _port_of(parsed)
    if port is not None and port not in ALLOWED_PORTS:
        raise UnsafeURLError("Only ports 80 and 443 are allowed.")
    effective_port = port or (443 if parsed.scheme.lower() == "https" else 80)

    addresses = await asyncio.to_thread(_resolve_sync, host, effective_port)
    if not addresses:
        raise UnsafeURLError(f"Could not resolve host '{host}'.")
    for address in addresses:
        if not is_public_ip(address):
            raise UnsafeURLError(
                "URL resolves to a private, loopback or reserved address."
            )
    return url


async def safe_get(
    client: httpx.AsyncClient, url: str, max_redirects: int = MAX_REDIRECTS
) -> httpx.Response:
    current = url
    for _ in range(max_redirects + 1):
        await ensure_safe_url(current)
        response = await client.get(current, follow_redirects=False)
        if not response.is_redirect:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        current = urljoin(str(response.url), location)
    raise UnsafeURLError("Too many redirects.")
