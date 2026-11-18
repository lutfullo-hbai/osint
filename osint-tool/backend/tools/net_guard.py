import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}
BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost", ".home.arpa")
MAX_REDIRECTS = 5
# a page or image fetched for analysis never needs more than this
MAX_RESPONSE_BYTES = 10 * 1024 * 1024


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


async def _check_url(url: str):
    """Validate a URL and return (parsed, host, addresses it resolves to)."""
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
    return parsed, host, sorted(addresses)


async def ensure_safe_url(url: str) -> str:
    await _check_url(url)
    return url


def _pinned(parsed, address: str) -> str:
    """The same URL with the host swapped for an already-validated IP."""
    netloc = f"[{address}]" if ":" in address else address
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return parsed._replace(netloc=netloc).geturl()


class ResponseTooLarge(UnsafeURLError):
    pass


async def _bounded_get(client: httpx.AsyncClient, url: str, max_bytes: int, **kwargs) -> httpx.Response:
    """Stream a response and stop once it grows past max_bytes."""
    async with client.stream("GET", url, **kwargs) as response:
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > max_bytes:
            raise ResponseTooLarge(f"Response is larger than {max_bytes // (1024 * 1024)} MB.")
        chunks, size = [], 0
        # decoded bytes: the limit also catches a small gzip that inflates hugely
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise ResponseTooLarge(f"Response is larger than {max_bytes // (1024 * 1024)} MB.")
            chunks.append(chunk)
        headers = [(k, v) for k, v in response.headers.multi_items()
                   if k.lower() not in ("content-length", "content-encoding", "transfer-encoding")]
        return httpx.Response(response.status_code, headers=headers, content=b"".join(chunks),
                              request=response.request, extensions=response.extensions)


async def safe_get(
    client: httpx.AsyncClient, url: str, max_redirects: int = MAX_REDIRECTS,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> httpx.Response:
    """GET a user-supplied URL without letting it reach a private address.

    The host is resolved and checked once, then the connection goes to that
    exact IP (Host header and TLS SNI keep the real name, so the certificate is
    still verified for it). Resolving again at connect time would let a DNS
    record flip to 127.0.0.1 between the check and the request (rebinding).
    """
    current = url
    for _ in range(max_redirects + 1):
        parsed, host, addresses = await _check_url(current)
        extensions = {"sni_hostname": host} if parsed.scheme.lower() == "https" else {}
        response = await _bounded_get(
            client,
            _pinned(parsed, addresses[0]),
            max_bytes,
            headers={"Host": parsed.netloc.rsplit("@", 1)[-1]},
            extensions=extensions,
            follow_redirects=False,
        )
        # report the URL the caller asked for, not the pinned IP form
        response.request = httpx.Request(response.request.method, current)
        if not response.is_redirect:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        current = urljoin(current, location)
    raise UnsafeURLError("Too many redirects.")
