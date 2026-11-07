import socket
import ssl
import sys
from urllib.parse import quote, urlparse

import dns.resolver
import requests

HEADERS = {"User-Agent": "osint-course/1.0 (educational use)"}
DNS_TYPES = ["A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA"]
SECURITY_HEADERS = [
    "strict-transport-security",
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
]


def normalize(target: str) -> str:
    target = target.strip().lower()
    if "://" in target:
        target = urlparse(target).hostname or target
    return target.strip("/.")


def dns_records(domain: str) -> dict[str, list[str]]:
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 5
    resolver.timeout = 5
    records = {}
    for record_type in DNS_TYPES:
        try:
            answers = resolver.resolve(domain, record_type, lifetime=5)
        except Exception:
            continue
        values = []
        for answer in answers:
            if record_type == "TXT":
                try:
                    values.append(b"".join(answer.strings).decode("utf-8", "ignore"))
                except Exception:
                    values.append(str(answer).strip('"'))
            elif record_type == "MX":
                exchange = str(answer.exchange).rstrip(".")
                values.append(exchange or "(null MX - email qabul qilinmaydi)")
            else:
                values.append(str(answer).rstrip("."))
        records[record_type] = values
    return records


def rdap_info(domain: str) -> dict | None:
    try:
        response = requests.get(
            f"https://rdap.org/domain/{domain}",
            headers=HEADERS,
            timeout=20,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None

    data = response.json()
    info = {"status": ", ".join(data.get("status", []))}

    for event in data.get("events", []):
        action = event.get("eventAction", "")
        if action in ("registration", "expiration", "last changed"):
            info[action] = event.get("eventDate", "")

    nameservers = [
        server.get("ldhName", "").rstrip(".")
        for server in data.get("nameservers", [])
        if server.get("ldhName")
    ]
    if nameservers:
        info["nameservers"] = ", ".join(nameservers)

    for entity in data.get("entities", []):
        if "registrar" not in entity.get("roles", []):
            continue
        vcard = entity.get("vcardArray") or []
        if len(vcard) > 1:
            for item in vcard[1]:
                if item[0] == "fn":
                    info["registrar"] = item[3]
                    break
    return info


def http_info(domain: str) -> dict | None:
    for scheme in ("https", "http"):
        try:
            response = requests.get(
                f"{scheme}://{domain}",
                headers=HEADERS,
                timeout=20,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        headers = {key.lower(): value for key, value in response.headers.items()}
        interesting = {}
        for key in ("server", "x-powered-by", "content-type"):
            if key in headers:
                interesting[key] = headers[key]
        missing = [name for name in SECURITY_HEADERS if name not in headers]
        return {
            "url": str(response.url),
            "status": response.status_code,
            "headers": interesting,
            "missing_security_headers": missing,
        }
    return None


def subdomains(domain: str) -> list[str]:
    entries = None
    for query in (f"%25.{quote(domain)}", quote(domain)):
        try:
            response = requests.get(
                f"https://crt.sh/?q={query}&output=json",
                headers=HEADERS,
                timeout=30,
            )
        except requests.RequestException:
            continue
        if response.status_code != 200:
            continue
        try:
            entries = response.json()
        except ValueError:
            continue
        if entries:
            break

    if not entries:
        return []

    names = set()
    for entry in entries:
        for name in str(entry.get("name_value", "")).splitlines():
            name = name.strip().lower().lstrip("*.")
            if name.endswith(domain):
                names.add(name)
    return sorted(names)


def tls_info(domain: str) -> dict | None:
    context = ssl.create_default_context()
    try:
        with socket.create_connection((domain, 443), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as tls:
                cert = tls.getpeercert()
    except (OSError, ssl.SSLError):
        return None

    subject = dict(item[0] for item in cert.get("subject", []))
    issuer = dict(item[0] for item in cert.get("issuer", []))
    san = [value for kind, value in cert.get("subjectAltName", []) if kind == "DNS"]
    return {
        "subject": subject.get("commonName", ""),
        "issuer": issuer.get("organizationName") or issuer.get("commonName", ""),
        "not_after": cert.get("notAfter", ""),
        "san": san[:15],
    }


def print_section(title: str) -> None:
    print(f"\n[{title}]")


def analyze(domain: str) -> None:
    print("=" * 56)
    print(f"Domen: {domain}")

    records = dns_records(domain)
    print_section("DNS")
    if not records:
        print("  DNS yozuvlari topilmadi.")
    for record_type, values in records.items():
        shown = values[:6]
        suffix = "" if len(values) <= 6 else f" (+{len(values) - 6} ta)"
        print(f"  {record_type}: {', '.join(shown)}{suffix}")

    print_section("RDAP / WHOIS")
    rdap = rdap_info(domain)
    if not rdap:
        print("  RDAP ma'lumoti olinmadi.")
    else:
        for key, value in rdap.items():
            print(f"  {key}: {value}")

    print_section("HTTP")
    http = http_info(domain)
    if not http:
        print("  Sayt javob bermadi.")
    else:
        print(f"  URL: {http['url']}")
        print(f"  Status: {http['status']}")
        for key, value in http["headers"].items():
            print(f"  {key}: {value}")
        if http["missing_security_headers"]:
            print(f"  Yetishmayotgan xavfsizlik sarlavhalari: {', '.join(http['missing_security_headers'])}")

    print_section("TLS sertifikat")
    tls = tls_info(domain)
    if not tls:
        print("  Sertifikat olinmadi.")
    else:
        print(f"  Subject: {tls['subject']}")
        print(f"  Issuer: {tls['issuer']}")
        print(f"  Amal qiladi: {tls['not_after']}")
        if tls["san"]:
            print(f"  SAN: {', '.join(tls['san'])}")

    print_section("Subdomenlar (crt.sh)")
    names = subdomains(domain)
    if not names:
        print("  Topilmadi yoki crt.sh javob bermadi.")
    else:
        for name in names[:20]:
            print(f"  - {name}")
        if len(names) > 20:
            print(f"  ... yana {len(names) - 20} ta")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Foydalanish: python3 {sys.argv[0]} <domen>")
        sys.exit(1)

    domain = normalize(sys.argv[1])
    if "." not in domain or " " in domain:
        print(f"[XATO] Noto'g'ri domen: {domain}")
        sys.exit(1)
    analyze(domain)


if __name__ == "__main__":
    main()
