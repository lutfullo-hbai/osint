import asyncio
import socket

import httpx

from tools.base import ToolError


def _reverse_dns_sync(ip_address: str) -> list[str]:
    try:
        primary, aliases, _ = socket.gethostbyaddr(ip_address)
    except OSError:
        return []
    return [name.lower().rstrip(".") for name in [primary, *aliases] if name]


async def reverse_dns_lookup(ip_address: str) -> tuple[dict, list[str]]:
    hostnames = await asyncio.to_thread(_reverse_dns_sync, ip_address)
    if not hostnames:
        raise ToolError("No PTR record for this IP.")
    entry = {
        "platform": "Reverse DNS",
        "url": "",
        "status": "found",
        "info": ", ".join(hostnames[:8]),
    }
    return entry, hostnames


def summarize_internetdb(ip_address: str, data: dict) -> dict:
    info_parts = []
    ports = data.get("ports") or []
    if ports:
        info_parts.append("Open ports: " + ", ".join(str(p) for p in ports[:30]))
    tags = data.get("tags") or []
    if tags:
        info_parts.append("Tags: " + ", ".join(tags[:10]))
    cpes = data.get("cpes") or []
    if cpes:
        info_parts.append("Software: " + ", ".join(cpes[:10]))
    vulns = data.get("vulns") or []
    if vulns:
        shown = ", ".join(vulns[:15])
        more = len(vulns) - 15
        info_parts.append(
            f"Known CVEs ({len(vulns)}): {shown}"
            + (f" +{more} more" if more > 0 else "")
        )
    return {
        "platform": "Shodan InternetDB",
        "url": f"https://www.shodan.io/host/{ip_address}",
        "status": "found",
        "info": "; ".join(info_parts) or "Indexed, but no ports or CVEs listed.",
    }


async def internetdb_lookup(
    client: httpx.AsyncClient, ip_address: str
) -> tuple[dict, list[str]]:
    """Read Shodan's existing index; this never probes the target itself."""
    response = await client.get(f"https://internetdb.shodan.io/{ip_address}")
    if response.status_code == 404:
        raise ToolError("IP is not in the Shodan index.")
    if response.status_code != 200:
        raise ToolError(f"HTTP {response.status_code}.")
    data = response.json()
    hostnames = [str(name).lower() for name in data.get("hostnames") or []]
    return summarize_internetdb(ip_address, data), hostnames


async def rdap_ip_lookup(client: httpx.AsyncClient, ip_address: str) -> dict:
    response = await client.get(f"https://rdap.org/ip/{ip_address}")
    if response.status_code != 200:
        raise ToolError(f"RDAP returned HTTP {response.status_code}.")
    data = response.json()

    info_parts = []
    if data.get("name"):
        info_parts.append(f"Network: {data['name']}")
    if data.get("startAddress") and data.get("endAddress"):
        info_parts.append(f"Range: {data['startAddress']} - {data['endAddress']}")
    if data.get("country"):
        info_parts.append(f"Country: {data['country']}")
    if data.get("type"):
        info_parts.append(f"Type: {data['type']}")
    return {
        "platform": "RDAP (IP network)",
        "url": f"https://client.rdap.org/?type=ip&object={ip_address}",
        "status": "found",
        "info": "; ".join(info_parts) or "Record retrieved",
    }
