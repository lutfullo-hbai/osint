"""Lightweight web-recon on a domain's own public files.

robots.txt / sitemap.xml / security.txt / favicon are all served by the target
itself, fetched through the SSRF guard. Disallowed robots paths and the Shodan
favicon hash are classic pivots for mapping a site and finding related hosts.
"""
import base64
import hashlib
import re
from urllib.parse import quote

import httpx

from tools.base import ToolError
from tools.net_guard import UnsafeURLError, safe_get

MAX_DISALLOW = 25
MAX_SITEMAP_PREVIEW = 5


def murmur3_32(data: bytes, seed: int = 0) -> int:
    """MurmurHash3 x86_32, signed output — matches Shodan's http.favicon.hash."""
    c1, c2 = 0xCC9E2D51, 0x1B873593
    length = len(data)
    h1 = seed & 0xFFFFFFFF
    rounded = (length // 4) * 4
    for i in range(0, rounded, 4):
        k1 = int.from_bytes(data[i:i + 4], "little")
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1
        h1 = ((h1 << 13) | (h1 >> 19)) & 0xFFFFFFFF
        h1 = (h1 * 5 + 0xE6546B64) & 0xFFFFFFFF
    k1 = 0
    tail = data[rounded:]
    if len(tail) >= 3:
        k1 ^= tail[2] << 16
    if len(tail) >= 2:
        k1 ^= tail[1] << 8
    if len(tail) >= 1:
        k1 ^= tail[0]
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1
    h1 ^= length
    h1 ^= h1 >> 16
    h1 = (h1 * 0x85EBCA6B) & 0xFFFFFFFF
    h1 ^= h1 >> 13
    h1 = (h1 * 0xC2B2AE35) & 0xFFFFFFFF
    h1 ^= h1 >> 16
    return h1 - 0x100000000 if h1 & 0x80000000 else h1


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        response = await safe_get(client, url)
    except (httpx.HTTPError, UnsafeURLError):
        return None
    return response if response.status_code == 200 else None


async def favicon_hash(client: httpx.AsyncClient, domain: str) -> dict:
    response = await _get(client, f"https://{domain}/favicon.ico")
    if response is None or not response.content:
        raise ToolError("No favicon served at /favicon.ico.")
    data = response.content
    shodan_hash = murmur3_32(base64.encodebytes(data))
    sha = hashlib.sha256(data).hexdigest()[:16]
    return {
        "platform": "Favicon hash",
        "url": f"https://www.shodan.io/search?query=http.favicon.hash%3A{shodan_hash}",
        "status": "found",
        "info": (
            f"Shodan favicon hash: {shodan_hash}; SHA-256: {sha}... "
            "Open the link to find other hosts serving the same icon."
        ),
    }


def parse_robots(text: str) -> list[str]:
    paths = []
    seen = set()
    for line in text.splitlines():
        match = re.match(r"(?i)\s*Disallow\s*:\s*(\S+)", line)
        if match:
            path = match.group(1).strip()
            if path and path != "/" and path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


async def disclosure_files(client: httpx.AsyncClient, domain: str) -> tuple[list[dict], list[str]]:
    results: list[dict] = []
    warnings: list[str] = []

    robots = await _get(client, f"https://{domain}/robots.txt")
    if robots is not None:
        paths = parse_robots(robots.text)
        info = f"{len(robots.text)} bytes."
        if paths:
            preview = ", ".join(paths[:MAX_DISALLOW])
            info += f" Disallowed paths ({len(paths)}): {preview}"
        results.append({
            "platform": "robots.txt",
            "url": f"https://{domain}/robots.txt",
            "status": "found",
            "info": info,
        })
    else:
        warnings.append("No robots.txt served.")

    security = await _get(client, f"https://{domain}/.well-known/security.txt")
    if security is not None:
        fields = []
        for line in security.text.splitlines():
            if re.match(r"(?i)\s*(Contact|Encryption|Policy|Expires)\s*:", line):
                fields.append(line.strip())
        results.append({
            "platform": "security.txt",
            "url": f"https://{domain}/.well-known/security.txt",
            "status": "found",
            "info": "; ".join(fields[:6]) or "Present.",
        })

    sitemap = await _get(client, f"https://{domain}/sitemap.xml")
    if sitemap is not None:
        locs = re.findall(r"<loc>\s*([^<\s]+)", sitemap.text)
        preview = ", ".join(locs[:MAX_SITEMAP_PREVIEW])
        results.append({
            "platform": "sitemap.xml",
            "url": f"https://{domain}/sitemap.xml",
            "status": "found",
            "info": f"{len(locs)} URL(s) listed. {preview}",
        })

    if not results:
        raise ToolError("No robots.txt, security.txt or sitemap.xml found.")
    return results, warnings
