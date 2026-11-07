import asyncio
import ssl
import time
from urllib.parse import quote

import httpx

from tools.base import ToolError
from tools.net_guard import UnsafeURLError, ensure_safe_url, safe_get

TLS_TIMEOUT_SECONDS = 10
CERT_EXPIRY_WARNING_DAYS = 14

TECH_SIGNATURES = {
    "Cloudflare": ["cloudflare", "__cf_bm", "cf-ray"],
    "nginx": ["nginx"],
    "Apache": ["apache"],
    "IIS": ["microsoft-iis"],
    "WordPress": ["wp-content", "wp-includes", "wordpress"],
    "Drupal": ["drupal"],
    "Joomla": ["joomla"],
    "Next.js": ["_next/", "__next_data__"],
    "React": ["data-reactroot", "react-dom", "__reactfiber"],
    "Vue.js": ["vue.js", "__vue__"],
    "Angular": ["ng-version"],
    "Shopify": ["shopify", "cdn.shopify.com"],
    "Wix": ["wix.com", "x-wix-"],
    "Squarespace": ["squarespace"],
    "Google Analytics": ["googletagmanager", "google-analytics", "gtag("],
    "Google Tag Manager": ["googletagmanager"],
    "PHP": ["x-powered-by: php", "phpsessid"],
    "ASP.NET": ["asp.net", "x-aspnet-version"],
    "CloudFront": ["cloudfront"],
    "Akamai": ["akamai"],
}


# These names are common in ordinary page text, so only headers count as evidence.
HEADER_ONLY_TECHNOLOGIES = {
    "Cloudflare", "nginx", "Apache", "IIS", "CloudFront", "Akamai",
}
SECURITY_HEADERS = {
    "strict-transport-security": "Strict-Transport-Security",
    "content-security-policy": "Content-Security-Policy",
    "x-frame-options": "X-Frame-Options",
    "x-content-type-options": "X-Content-Type-Options",
    "referrer-policy": "Referrer-Policy",
    "permissions-policy": "Permissions-Policy",
}


def detect_technologies(headers: dict[str, str], body: str) -> list[str]:
    header_text = " ".join(
        f"{key}: {value}" for key, value in headers.items()
    ).lower()
    full_text = header_text + " " + body[:200_000].lower()
    found = []
    for technology, needles in TECH_SIGNATURES.items():
        haystack = (
            header_text if technology in HEADER_ONLY_TECHNOLOGIES else full_text
        )
        if any(needle in haystack for needle in needles):
            found.append(technology)
    return sorted(found)


def audit_security_headers(headers: dict[str, str]) -> tuple[list[str], list[str]]:
    csp = headers.get("content-security-policy", "").lower()
    present = []
    missing = []
    for key, label in SECURITY_HEADERS.items():
        covered = key in headers or (
            key == "x-frame-options" and "frame-ancestors" in csp
        )
        (present if covered else missing).append(label)
    return present, missing


def summarize_cert(cert: dict, tls_version: str | None, now: float | None = None) -> str:
    issuer = {
        key: value for field in cert.get("issuer", ()) for key, value in field
    }
    parts = [f"Issuer: {issuer.get('organizationName') or issuer.get('commonName') or 'unknown'}"]
    if tls_version:
        parts.append(f"Protocol: {tls_version}")
    not_after = cert.get("notAfter")
    if not_after:
        expires = ssl.cert_time_to_seconds(not_after)
        days_left = int((expires - (time.time() if now is None else now)) // 86400)
        note = " - RENEWAL DUE" if days_left < CERT_EXPIRY_WARNING_DAYS else ""
        parts.append(f"Expires: {not_after} ({days_left} day(s) left{note})")
    sans = [value for kind, value in cert.get("subjectAltName", ()) if kind == "DNS"]
    if sans:
        parts.append(f"SANs ({len(sans)}): {', '.join(sans[:10])}")
    return "; ".join(parts)


async def tls_lookup(domain: str) -> dict:
    try:
        await ensure_safe_url(f"https://{domain}")
    except UnsafeURLError as exc:
        raise ToolError(str(exc)) from exc

    entry = {
        "platform": "TLS certificate",
        "url": f"https://{domain}",
        "status": "found",
    }
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(
                domain, 443, ssl=ssl.create_default_context(), server_hostname=domain
            ),
            TLS_TIMEOUT_SECONDS,
        )
    except ssl.SSLCertVerificationError as exc:
        return {
            **entry,
            "info": f"Certificate verification FAILED: {exc.verify_message}",
        }
    except (OSError, asyncio.TimeoutError) as exc:
        raise ToolError(f"No TLS connection on port 443 ({type(exc).__name__}).") from exc

    try:
        cert = writer.get_extra_info("peercert") or {}
        tls_object = writer.get_extra_info("ssl_object")
        return {
            **entry,
            "info": summarize_cert(cert, tls_object.version() if tls_object else None),
        }
    finally:
        writer.close()


async def urlscan_lookup(client: httpx.AsyncClient, domain: str) -> dict:
    response = await client.get(
        f"https://urlscan.io/api/v1/search/?q=domain:{quote(domain)}&size=10"
    )
    if response.status_code == 429:
        raise ToolError("urlscan.io rate limit reached.")
    if response.status_code != 200:
        raise ToolError(f"urlscan.io returned HTTP {response.status_code}.")
    data = response.json()
    total = data.get("total", 0)
    if not total:
        raise ToolError("urlscan.io has no scans for this domain.")

    recent = []
    for item in (data.get("results") or [])[:3]:
        page = item.get("page") or {}
        if page.get("url"):
            recent.append(page["url"])
    info = f"{total} scan(s) found."
    if recent:
        info += " Recent: " + ", ".join(recent)
    return {
        "platform": "urlscan.io",
        "url": f"https://urlscan.io/domain/{domain}",
        "status": "found",
        "info": info,
    }


async def wayback_lookup(client: httpx.AsyncClient, domain: str) -> dict:
    response = await client.get(
        f"https://archive.org/wayback/available?url={quote(domain)}"
    )
    if response.status_code != 200:
        raise ToolError(f"Wayback Machine returned HTTP {response.status_code}.")
    data = response.json()
    closest = (data.get("archived_snapshots") or {}).get("closest")
    if not closest:
        raise ToolError("Wayback Machine has no snapshot for this domain.")
    snapshot_url = closest.get("url") or ""
    timestamp = closest.get("timestamp") or ""
    info = "Latest snapshot available."
    if timestamp:
        info = f"Latest snapshot: {timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}."
    return {
        "platform": "Wayback Machine",
        "url": snapshot_url,
        "status": "found",
        "info": info,
    }


async def http_fingerprint(client: httpx.AsyncClient, domain: str) -> dict:
    last_error = "unknown error"
    for scheme in ("https", "http"):
        try:
            response = await safe_get(client, f"{scheme}://{domain}")
        except (httpx.HTTPError, UnsafeURLError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue

        headers = {key.lower(): value for key, value in response.headers.items()}
        technologies = detect_technologies(headers, response.text)
        info_parts = [f"HTTP {response.status_code}"]
        if headers.get("server"):
            info_parts.append(f"Server: {headers['server']}")
        if headers.get("x-powered-by"):
            info_parts.append(f"Powered by: {headers['x-powered-by']}")
        if technologies:
            info_parts.append("Tech: " + ", ".join(technologies))
        present, missing = audit_security_headers(headers)
        grade = f"Security headers: {len(present)}/{len(SECURITY_HEADERS)}"
        info_parts.append(
            f"{grade} (missing: {', '.join(missing)})" if missing else grade
        )
        return {
            "platform": "HTTP fingerprint",
            "url": str(response.url),
            "status": "found",
            "info": "; ".join(info_parts),
        }

    raise ToolError(f"Could not fetch the website ({last_error}).")
