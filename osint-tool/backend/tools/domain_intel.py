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
    if not DOMAIN_RE.fullmatch(domain):
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
    for record_type in ("A", "MX", "NS", "TXT"):
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


async def crtsh_lookup(client: httpx.AsyncClient, domain: str) -> dict:
    response = await client.get(
        f"https://crt.sh/?q=%.{domain}&output=json",
        timeout=httpx.Timeout(30.0),
    )
    if response.status_code != 200:
        raise ToolError(f"crt.sh returned HTTP {response.status_code}.")

    try:
        rows = response.json()
    except ValueError as exc:
        raise ToolError("crt.sh returned malformed JSON.") from exc

    subdomains = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        for line in str(row.get("name_value", "")).splitlines():
            name = line.strip().lstrip("*.").lower()
            if name.endswith(domain) and name != domain:
                subdomains.add(name)

    if not subdomains:
        raise ToolError("No certificate-transparency subdomains found.")
    ordered = sorted(subdomains)
    preview = ", ".join(ordered[:25]) + (" ..." if len(ordered) > 25 else "")
    return {
        "platform": "Subdomains (crt.sh)",
        "url": f"https://crt.sh/?q=%.{domain}",
        "status": "found",
        "info": f"{len(subdomains)} unique subdomains: {preview}",
    }


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
