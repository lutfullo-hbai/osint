import asyncio
import re

import httpx

from tools.base import ToolError

DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})+$"
)
HEADERS = {"User-Agent": "osint-tool/1.0 (local self-audit)"}
DEFAULT_TIMEOUT = httpx.Timeout(15.0)


class DomainValidationError(ValueError):
    pass


def normalize_domain(raw: str) -> str:
    domain = raw.strip().lower()
    domain = re.sub(r"^https?://", "", domain)
    domain = domain.split("/")[0].split(":")[0].strip(".")
    if not DOMAIN_RE.fullmatch(domain) or domain.rsplit(".", 1)[-1].isdigit():
        raise DomainValidationError(
            f"'{raw}' is not a valid domain name (e.g. example.com)."
        )
    return domain


async def rdap_lookup(client: httpx.AsyncClient, domain: str) -> dict:
    response = await client.get(f"https://rdap.org/domain/{domain}")
    if response.status_code == 404:
        raise ToolError("No RDAP record found (domain may not be registered).")
    if response.status_code != 200:
        raise ToolError(f"RDAP returned HTTP {response.status_code}.")
    data = response.json()

    events = {}
    for event in data.get("events") or []:
        if isinstance(event, dict) and event.get("eventAction"):
            events[event["eventAction"]] = str(event.get("eventDate", ""))[:10]

    registrar = ""
    for entity in data.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        if "registrar" in (entity.get("roles") or []):
            vcard = entity.get("vcardArray") or []
            if len(vcard) > 1:
                for field in vcard[1]:
                    if isinstance(field, list) and len(field) > 3 and field[0] == "fn":
                        registrar = str(field[3] or "").strip()

    nameservers = [
        str(ns.get("ldhName", "")).lower()
        for ns in (data.get("nameservers") or [])
        if isinstance(ns, dict) and ns.get("ldhName")
    ]
    statuses = [str(s) for s in (data.get("status") or [])][:4]

    info_parts = []
    if registrar:
        info_parts.append(f"Registrar: {registrar}")
    if "registration" in events:
        info_parts.append(f"Registered: {events['registration']}")
    if "expiration" in events:
        info_parts.append(f"Expires: {events['expiration']}")
    if nameservers:
        info_parts.append("Nameservers: " + ", ".join(nameservers[:6]))
    if statuses:
        info_parts.append("Status: " + ", ".join(statuses))

    return {
        "platform": "RDAP / Whois",
        "url": f"https://client.rdap.org/?type=domain&object={domain}",
        "status": "found",
        "info": "; ".join(info_parts) or "Record retrieved",
    }


def _dns_sync(domain: str) -> list[tuple[str, list[str]]]:
    import dns.resolver

    resolver = dns.resolver.Resolver()
    resolver.lifetime = 5
    resolver.timeout = 5

    collected = []
    for record_type in ("A", "AAAA", "CNAME", "MX", "NS", "SOA", "CAA", "TXT"):
        try:
            answers = resolver.resolve(domain, record_type)
        except Exception:
            continue
        values = []
        for record in answers:
            value = str(record).strip()
            if record_type == "TXT":
                value = value.strip('"')[:150]
            values.append(value)
        if values:
            collected.append((record_type, values[:8]))
    return collected


async def dns_lookup(domain: str) -> tuple[dict, str]:
    records = await asyncio.to_thread(_dns_sync, domain)
    if not records:
        raise ToolError("No DNS records resolved.")

    first_ipv4 = next(
        (values[0] for record_type, values in records if record_type == "A"),
        "",
    )
    info = " | ".join(
        f"{record_type}: {', '.join(values)}" for record_type, values in records
    )
    entry = {
        "platform": "DNS records",
        "url": f"https://dnschecker.org/#A/{domain}",
        "status": "found",
        "info": info,
    }
    return entry, first_ipv4


def is_subdomain(name: str, domain: str) -> bool:
    return name.endswith(f".{domain}")


def parse_crtsh(rows, domain: str) -> set[str]:
    subdomains = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        for line in str(row.get("name_value", "")).splitlines():
            name = line.strip().removeprefix("*.").lower()
            if is_subdomain(name, domain):
                subdomains.add(name)
    return subdomains


async def _crtsh_subdomains(client: httpx.AsyncClient, domain: str) -> set[str]:
    response = await client.get(
        f"https://crt.sh/?q=%.{domain}&output=json",
        timeout=httpx.Timeout(30.0),
    )
    if response.status_code != 200:
        raise ToolError(f"HTTP {response.status_code}")
    try:
        return parse_crtsh(response.json(), domain)
    except ValueError as exc:
        raise ToolError("malformed JSON") from exc


async def _otx_subdomains(client: httpx.AsyncClient, domain: str) -> set[str]:
    response = await client.get(
        f"https://otx.alienvault.com/api/v1/indicators/domain/{domain}/passive_dns",
        timeout=httpx.Timeout(20.0),
    )
    if response.status_code != 200:
        raise ToolError(f"HTTP {response.status_code}")
    records = response.json().get("passive_dns") or []
    names = {str(record.get("hostname", "")).lower() for record in records}
    return {name for name in names if is_subdomain(name, domain)}


async def _hackertarget_subdomains(client: httpx.AsyncClient, domain: str) -> set[str]:
    response = await client.get(
        f"https://api.hackertarget.com/hostsearch/?q={domain}"
    )
    if response.status_code != 200:
        raise ToolError(f"HTTP {response.status_code}")
    # Quota and error messages also arrive as HTTP 200 plain text.
    if "," not in response.text:
        raise ToolError(response.text.strip()[:80] or "empty response")
    names = {line.split(",")[0].strip().lower() for line in response.text.splitlines()}
    return {name for name in names if is_subdomain(name, domain)}


async def subdomain_lookup(
    client: httpx.AsyncClient, domain: str
) -> tuple[dict, list[str], list[str]]:
    """Union several passive sources, since each one is often down or rate limited."""
    sources = {
        "crt.sh": _crtsh_subdomains,
        "AlienVault OTX": _otx_subdomains,
        "HackerTarget": _hackertarget_subdomains,
    }
    outcomes = await asyncio.gather(
        *(fetch(client, domain) for fetch in sources.values()),
        return_exceptions=True,
    )

    found: set[str] = set()
    used = []
    warnings = []
    for label, outcome in zip(sources, outcomes):
        if isinstance(outcome, ToolError):
            warnings.append(f"{label}: {outcome}")
        elif isinstance(outcome, BaseException):
            warnings.append(f"{label}: {type(outcome).__name__}")
        else:
            found |= outcome
            used.append(f"{label} ({len(outcome)})")

    if not found:
        raise ToolError(
            "; ".join(warnings) or "No passive subdomains found in any source."
        )
    ordered = sorted(found)
    preview = ", ".join(ordered[:25]) + (" ..." if len(ordered) > 25 else "")
    entry = {
        "platform": "Subdomains",
        "url": f"https://crt.sh/?q=%.{domain}",
        "status": "found",
        "info": f"{len(ordered)} unique from {', '.join(used)}: {preview}",
    }
    return entry, ordered, warnings


async def ip_geo_lookup(client: httpx.AsyncClient, ip_address: str) -> dict:
    if not ip_address:
        raise ToolError("No IPv4 address resolved for geolocation.")
    response = await client.get(
        f"http://ip-api.com/json/{ip_address}"
        "?fields=status,message,country,regionName,city,isp,org,as,query"
    )
    if response.status_code != 200:
        raise ToolError(f"ip-api.com returned HTTP {response.status_code}.")
    data = response.json()
    if data.get("status") != "success":
        raise ToolError(
            f"ip-api.com failed: {data.get('message') or 'unknown error'}"
        )

    location = ", ".join(
        part
        for part in (
            data.get("country"),
            data.get("regionName"),
            data.get("city"),
        )
        if part
    )
    info_parts = [f"IP: {data.get('query', ip_address)}"]
    if location:
        info_parts.append(f"Location: {location}")
    if data.get("isp"):
        info_parts.append(f"ISP: {data['isp']}")
    if data.get("as"):
        info_parts.append(f"AS: {data['as']}")

    return {
        "platform": "IP geolocation",
        "url": f"https://ip-api.com/#{ip_address}",
        "status": "found",
        "info": "; ".join(info_parts),
    }
