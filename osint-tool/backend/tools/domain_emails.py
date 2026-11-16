"""Email addresses an organisation has published on the open web.

theHarvester's key-free core, done with our own search backend: search for
"@domain" and keep only addresses at that domain that actually appear in a
result's title or snippet, each with the page that shows it. Nothing is
guessed (no first.last@ patterns) and nothing is probed.
"""
from __future__ import annotations

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


async def find_domain_emails(domain: str) -> list[dict]:
    # "@gmail.com" would list random strangers, not this organisation
    if is_hub_domain(domain):
        return []
    quoted = f'"@{domain}"'
    batches = [quoted, f"{quoted} contact OR email OR aloqa OR kontakt"]
    items = await search_public(batches, max_results_per_batch=20)
    return extract_domain_emails(items, domain)
