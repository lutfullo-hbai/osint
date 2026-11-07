import asyncio
import hashlib

import httpx

RESOLVER_TIMEOUT = 5
GRAVATAR_URL = "https://www.gravatar.com/avatar/{digest}?d=404&s=200"


def _txt_records(resolver, name: str) -> list[str]:
    records = []
    try:
        answers = resolver.resolve(name, "TXT", lifetime=RESOLVER_TIMEOUT)
    except Exception:
        return records
    for answer in answers:
        try:
            records.append(b"".join(answer.strings).decode("utf-8", "ignore"))
        except Exception:
            records.append(str(answer).strip('"'))
    return records


def gather_dns_records(domain: str) -> dict:
    import dns.resolver

    resolver = dns.resolver.Resolver()
    resolver.lifetime = RESOLVER_TIMEOUT
    resolver.timeout = RESOLVER_TIMEOUT

    mx_records = []
    try:
        answers = resolver.resolve(domain, "MX", lifetime=RESOLVER_TIMEOUT)
        mx_records = [str(answer.exchange).rstrip(".") for answer in answers]
    except Exception:
        pass

    return {
        "mx": mx_records,
        "txt": _txt_records(resolver, domain),
        "dmarc": _txt_records(resolver, f"_dmarc.{domain}"),
    }


def summarize_auth(records: dict) -> tuple[list[dict], list[str]]:
    results: list[dict] = []
    warnings: list[str] = []

    mx_records = records.get("mx") or []
    if mx_records:
        results.append(
            {
                "platform": "MX records",
                "status": "found",
                "info": ", ".join(mx_records[:6]),
            }
        )
    else:
        warnings.append(
            "No MX records found - this domain may not receive email."
        )

    txt_records = records.get("txt") or []
    dmarc_records = records.get("dmarc") or []
    spf = next(
        (record for record in txt_records if record.lower().startswith("v=spf1")),
        "",
    )
    dmarc = next(
        (record for record in dmarc_records if record.lower().startswith("v=dmarc1")),
        "",
    )

    auth_parts = [
        f"SPF: {'yes' if spf else 'no'}",
        f"DMARC: {'yes' if dmarc else 'no'}",
    ]
    if spf:
        auth_parts.append(f"SPF policy: {spf[:160]}")
    if dmarc:
        auth_parts.append(f"DMARC policy: {dmarc[:160]}")
    results.append(
        {
            "platform": "Email authentication",
            "status": "found",
            "info": " | ".join(auth_parts),
        }
    )

    if not spf:
        warnings.append("No SPF record found - sender spoofing may be easier.")
    if not dmarc:
        warnings.append("No DMARC record found - domain has no DMARC policy.")

    return results, warnings


async def domain_mail_intel(domain: str) -> tuple[list[dict], list[str]]:
    records = await asyncio.to_thread(gather_dns_records, domain)
    return summarize_auth(records)


async def email_domain_intel(email: str) -> tuple[list[dict], list[str]]:
    return await domain_mail_intel(email.rsplit("@", 1)[-1].lower())


async def gravatar_lookup(email: str) -> dict | None:
    digest = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()
    url = GRAVATAR_URL.format(digest=digest)
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        response = await client.get(url)
    if response.status_code == 200:
        return {
            "platform": "Gravatar",
            "url": url,
            "status": "found",
            "info": "A public Gravatar image is registered for this email.",
        }
    return None
