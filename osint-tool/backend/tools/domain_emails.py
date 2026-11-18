"""Email addresses an organisation has published on the open web.

theHarvester's key-free core, done with our own search backend: search for
"@domain" and keep only addresses at that domain that actually appear in a
result's title or snippet, each with the page that shows it. Nothing is
guessed (no first.last@ patterns) and nothing is probed.
"""
from __future__ import annotations

import asyncio
import re

from tools.hub_domains import is_hub_domain
from tools.public_search import search_public

MAX_EMAILS = 25
ROLE_LOCALPARTS = {
    "info", "admin", "contact", "support", "hello", "office", "sales", "mail",
    "team", "help", "noreply", "no-reply", "press", "hr", "jobs", "billing",
    "marketing", "pr", "media", "webmaster", "abuse", "security", "privacy",
    "reception", "kadr", "kadrlar", "devonxona", "murojaat",
}


_LIST_WORDS = ("announce", "list", "sig", "dev", "users", "news", "bounce",
               "noreply", "no-reply", "notify", "alerts", "digest", "subscribe")
_PERSONLIKE_RE = re.compile(r"^[a-z]{2,}[._-][a-z]{2,}$|^[a-z][._-]?[a-z]{3,}\d{0,4}$")


def address_kind(local: str) -> str:
    """role/list address, looks personal, or just "address" when unclear."""
    local = local.lower()
    if local in ROLE_LOCALPARTS or any(word in local for word in _LIST_WORDS):
        return "role or list address"
    if "." in local or "_" in local or "-" in local:
        if _PERSONLIKE_RE.match(local):
            return "looks personal"
    return "address"


def extract_domain_emails(items: list[dict], domain: str) -> list[dict]:
    """Addresses at the domain (or its subdomains) that a result really shows."""
    domain = domain.lower()
    pattern = re.compile(
        r"[A-Za-z0-9._%+\-]+@(?:[A-Za-z0-9\-]+\.)*" + re.escape(domain) + r"\b",
        re.IGNORECASE,
    )
    found: dict[str, dict] = {}
    for item in items:
        text = f"{item.get('title', '')} {item.get('info', '')}"
        for match in pattern.findall(text):
            email = match.lower().strip(".")
            if email in found or len(found) >= MAX_EMAILS:
                continue
            kind = address_kind(email.split("@", 1)[0])
            found[email] = {
                "platform": "Published email",
                "url": item.get("url", ""),
                "status": "found",
                "title": email,
                "email": email,
                "info": f"{email} ({kind}) — shown on: {(item.get('title') or item.get('url', ''))[:120]}",
                "source": "web_search",
            }
    return list(found.values())


def _entry(email: str, how: str, where: str, domain: str) -> dict:
    local, _, host = email.partition("@")
    own = host == domain or host.endswith("." + domain)
    kind = "administrative address" if where.startswith("DNS ") else address_kind(local)
    note = "" if own else f" (at another provider: {host})"
    caution = ("; personal-looking address — use only for this investigation's purpose"
               if kind == "looks personal" else "")
    return {
        "platform": "Published email",
        "url": where if where.startswith("http") else "",
        "status": "found",
        "title": email,
        "email": email,
        "info": f"{email} ({kind}{note}) — {how}: {where}{caution}",
        # DMARC/SOA addresses are often a DNS or mail-security provider's and
        # repeat across thousands of unrelated domains: not identity evidence
        "source": "dns_contact" if where.startswith("DNS ") else "published_contact",
    }


async def find_domain_emails(domain: str) -> list[dict]:
    """Addresses the organisation published: search snippets, security.txt,
    DMARC/SOA records and its own contact pages. Merged, each with its source."""
    from tools import site_contacts

    # "@gmail.com" would list random strangers, not this organisation
    if is_hub_domain(domain):
        return []

    async def from_search():
        quoted = f'"@{domain}"'
        items = await search_public([quoted, f"{quoted} contact OR email OR aloqa OR kontakt"],
                                    max_results_per_batch=20)
        return [(e["email"], "seen in a search result", e["url"] or "web search")
                for e in extract_domain_emails(items, domain)]

    async def from_security_txt():
        import httpx
        from tools.net_guard import safe_get
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=False,
                                     headers={"User-Agent": site_contacts.USER_AGENT}) as client:
            for path in ("/.well-known/security.txt", "/security.txt"):
                try:
                    response = await safe_get(client, f"https://{domain}{path}")
                except Exception:  # noqa: BLE001
                    continue
                if response.status_code == 200 and "contact:" in response.text.lower():
                    url = f"https://{domain}{path}"
                    return [(e, "security contact (security.txt, RFC 9116)", url)
                            for e in site_contacts.parse_security_txt(response.text)]
        return []

    async def from_crawl():
        found, _notes = await site_contacts.crawl_contacts(domain)
        return found

    # first-hand sources first: when an address appears in several places,
    # the organisation's own security.txt or website is the one cited
    outcomes = await asyncio.gather(from_security_txt(), from_crawl(),
                                    site_contacts.dns_contacts(domain), from_search(),
                                    return_exceptions=True)
    merged: dict[str, dict] = {}
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            continue
        for email, how, where in outcome:
            if email in merged or len(merged) >= MAX_EMAILS:
                continue
            merged[email] = _entry(email, how, where, domain)
    return list(merged.values())
