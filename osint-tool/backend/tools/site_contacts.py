"""Contact addresses an organisation publishes about itself, from its own
domain: security.txt (RFC 9116), DNS (DMARC report addresses, SOA admin) and a
polite crawl of its contact / about pages.

Rules for the crawl: robots.txt is obeyed, at most MAX_PAGES pages, a pause
between requests, an identifying User-Agent, only pages on the same host whose
link or path looks like a contact page, and the crawl stops at any sign of a
login wall or anti-bot challenge. Addresses are only read, never guessed.
"""
from __future__ import annotations

import asyncio
import re
from html import unescape
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from tools.net_guard import UnsafeURLError, safe_get

USER_AGENT = "osint-tool/1.0 (self-hosted research; contact-page reader)"
MAX_PAGES = 8
PAUSE_SECONDS = 2.0
TIMEOUT = httpx.Timeout(12.0)
MAX_BYTES = 2 * 1024 * 1024

CONTACT_WORDS = (
    "contact", "kontakt", "aloqa", "boglanish", "bog-lanish", "bog'lanish", "about", "biz-haqimizda",
    "haqimizda", "impressum", "team", "jamoa", "rahbariyat", "management", "leadership",
    "контакт", "связ", "о-нас", "o-nas", "о компании", "руководство", "privacy",
)
CHALLENGE_MARKERS = ("captcha", "cf-chl", "challenge-platform", "ddos-guard", "please enable javascript",
                     "verify you are human", "access denied")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+\-]+)\s*[\[\(\{]\s*(?:at|@)\s*[\]\)\}]\s*([A-Za-z0-9\-]+(?:\s*[\[\(\{]\s*(?:dot|\.)\s*[\]\)\}]\s*[A-Za-z0-9\-]+)+)",
    re.IGNORECASE)
_HREF_RE = re.compile(r"""<a\b[^>]*href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.IGNORECASE | re.DOTALL)
_ASSET_TAIL = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")


def emails_in(text: str) -> set[str]:
    """Plain and lightly obfuscated addresses ("name [at] example [dot] uz")."""
    found = {m.lower().strip(".") for m in _EMAIL_RE.findall(text or "")}
    for local, rest in _OBFUSCATED_RE.findall(text or ""):
        domain = re.sub(r"\s*[\[\(\{]\s*(?:dot|\.)\s*[\]\)\}]\s*", ".", rest, flags=re.IGNORECASE)
        found.add(f"{local}@{domain}".lower())
    return {e for e in found if not e.endswith(_ASSET_TAIL)}


def parse_security_txt(text: str) -> set[str]:
    out = set()
    for line in (text or "").splitlines():
        if line.lower().startswith("contact:"):
            out |= emails_in(line.split(":", 1)[1].replace("mailto:", " "))
    return out


def parse_dmarc(txt: str) -> set[str]:
    out = set()
    for tag in ("rua", "ruf"):
        m = re.search(tag + r"\s*=\s*([^;]+)", txt or "", re.IGNORECASE)
        if m:
            for part in m.group(1).split(","):
                part = part.strip()
                if part.lower().startswith("mailto:"):
                    out |= emails_in(part[7:].split("!")[0])
    return out


def soa_rname_to_email(rname: str) -> str | None:
    """'hostmaster.example.uz.' -> 'hostmaster@example.uz' (escaped dots kept)."""
    rname = (rname or "").rstrip(".")
    m = re.match(r"^((?:[^.\\]|\\.)+)\.(.+)$", rname)
    if not m:
        return None
    local = m.group(1).replace("\\.", ".")
    email = f"{local}@{m.group(2)}".lower()
    return email if _EMAIL_RE.fullmatch(email) else None


def _dns_sync(domain: str) -> tuple[list[str], str | None]:
    import dns.resolver
    resolver = dns.resolver.Resolver()
    resolver.lifetime = resolver.timeout = 5
    dmarc, soa = [], None
    try:
        dmarc = [str(r).strip('"') for r in resolver.resolve(f"_dmarc.{domain}", "TXT")]
    except Exception:  # noqa: BLE001
        pass
    try:
        soa = str(resolver.resolve(domain, "SOA")[0].rname)
    except Exception:  # noqa: BLE001
        pass
    return dmarc, soa


async def dns_contacts(domain: str) -> list[tuple[str, str, str]]:
    """[(email, how, where)] from DMARC and SOA."""
    dmarc, soa = await asyncio.to_thread(_dns_sync, domain)
    out = []
    for txt in dmarc:
        for email in parse_dmarc(txt):
            out.append((email, "DMARC report address (may belong to a mail-security vendor)",
                        f"DNS TXT _dmarc.{domain}"))
    email = soa_rname_to_email(soa or "")
    if email:
        out.append((email, "DNS zone administrator (SOA record)", f"DNS SOA {domain}"))
    return out


def _looks_blocked(response: httpx.Response) -> bool:
    if response.status_code in (401, 403, 429, 503):
        return True
    head = response.text[:4000].lower() if "text" in response.headers.get("content-type", "") else ""
    return any(marker in head for marker in CHALLENGE_MARKERS)


def contact_links(html: str, base_url: str) -> list[str]:
    host = urlparse(base_url).hostname
    links = []
    for href, label in _HREF_RE.findall(html or ""):
        url = urljoin(base_url, unescape(href.strip()))
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or parsed.hostname != host:
            continue
        haystack = (parsed.path + " " + re.sub(r"<[^>]+>", " ", label)).lower()
        if any(word in haystack for word in CONTACT_WORDS) and url not in links:
            links.append(url.split("#")[0])
    return links


async def crawl_contacts(domain: str) -> tuple[list[tuple[str, str, str]], list[str]]:
    """[(email, how, page)] from the site's own contact pages, plus notes."""
    found, notes = [], []
    base = f"https://{domain}/"
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT},
                                 follow_redirects=False) as client:
        robots = RobotFileParser()
        try:
            r = await safe_get(client, urljoin(base, "/robots.txt"))
            robots.parse(r.text.splitlines() if r.status_code == 200 else [])
        except (httpx.HTTPError, UnsafeURLError):
            robots.parse([])

        queue, seen = [base], set()
        while queue and len(seen) < MAX_PAGES:
            url = queue.pop(0)
            if url in seen:
                continue
            if not robots.can_fetch(USER_AGENT, url):
                notes.append(f"robots.txt disallows {urlparse(url).path or '/'}")
                seen.add(url)
                continue
            if seen:
                await asyncio.sleep(PAUSE_SECONDS)
            seen.add(url)
            try:
                response = await safe_get(client, url)
            except (httpx.HTTPError, UnsafeURLError) as exc:
                notes.append(f"{url}: {type(exc).__name__}")
                continue
            if _looks_blocked(response):
                notes.append(f"stopped: {url} answered with a login wall or anti-bot check")
                break
            if response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
                continue
            html = response.text[:MAX_BYTES]
            mailtos = {m.lower() for m in re.findall(r"mailto:([^\"'?\s>]+)", html, re.IGNORECASE)}
            text = re.sub(r"<[^>]+>", " ", unescape(html))
            for email in (emails_in(" ".join(mailtos)) | emails_in(text)):
                found.append((email, "published on the organisation's own website", str(response.url)))
            if url == base:
                queue.extend(link for link in contact_links(html, str(response.url)) if link not in seen)
    return found, notes
