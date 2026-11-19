"""Contact extractor (ROADMAP 7.7, the Photon idea in our own code).

From a page someone published about themselves (a personal site, a
channel's description, a classified ad, a "Contact" page) it reads the
e-mail addresses, phone numbers, social-profile links and websites that are
written there, each with the URL of the page it was read on.

Two entry points:
  contacts_from_text(text, page_url)  - text already fetched (a bio, a
                                        channel description): no network
  extract_contacts(url)               - the page plus up to MAX_PAGES pages it
                                        links to on the same site, 1 level deep

Crawl rules: every request goes through safe_get (no private addresses,
size cap), robots.txt is obeyed (unreachable robots.txt = no crawl), a pause
between requests, an identifying User-Agent, and the crawl stops at a login
wall or anti-bot check. Values are only read, never guessed or completed.
"""
from __future__ import annotations

import asyncio
import re
from html import unescape
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import phonenumbers

from services.correlate import handle_from_url
from tools.hub_domains import is_hub_domain
from tools.net_guard import UnsafeURLError, safe_get
from tools.site_contacts import CONTACT_WORDS, _looks_blocked, emails_in

USER_AGENT = "osint-tool/1.0 (self-hosted research; contact extractor)"
MAX_PAGES = 10
PAUSE_SECONDS = 1.0
TIMEOUT = httpx.Timeout(12.0)
MAX_BYTES = 2 * 1024 * 1024
MAX_PER_KIND = 15
DEFAULT_REGION = "UZ"           # "90 123 45 67" written without +998

_HREF_RE = re.compile(r"""<a\b[^>]*href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.IGNORECASE | re.DOTALL)
_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]+", re.IGNORECASE)
_TEL_RE = re.compile(r"""href=["']tel:([^"']+)["']""", re.IGNORECASE)
_MAILTO_RE = re.compile(r"""mailto:([^"'?\s>]+)""", re.IGNORECASE)
_SKIP_TAGS_RE = re.compile(r"<(script|style|noscript|svg)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
# messenger links that carry a handle or a number in the path
_MESSENGER_RE = re.compile(r"^https?://(?:www\.)?(t\.me|telegram\.me|wa\.me|api\.whatsapp\.com)/", re.IGNORECASE)
_SKIP_SITES = ("schema.org", "w3.org", "googleapis.com", "gstatic.com", "googletagmanager.com",
               "google-analytics.com", "cloudflare.com", "jsdelivr.net", "fonts.", "cdn.",
               # app-store and share links are not the person's own site
               "apps.apple.com", "itunes.apple.com", "play.google.com", "appgallery.huawei.com",
               "addtoany.com", "sharethis.com")


def _strip_html(html: str) -> str:
    text = _SKIP_TAGS_RE.sub(" ", html or "")
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", text, flags=re.IGNORECASE)
    return unescape(re.sub(r"<[^>]+>", " ", text))


def phones_in(text: str, region: str = DEFAULT_REGION) -> set[str]:
    """Valid phone numbers written in the text, as E.164 (+998901234567).

    phonenumbers' validity check (real country code, right length, valid
    prefix) keeps dates, prices, IDs and order numbers out.
    """
    found = set()
    try:
        for match in phonenumbers.PhoneNumberMatcher(text or "", region,
                                                     leniency=phonenumbers.Leniency.VALID):
            found.add(phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164))
    except Exception:  # noqa: BLE001 - a parser hiccup must not lose the other values
        pass
    return found


def _link_kind(url: str, page_host: str) -> tuple[str, str] | None:
    """('social', 'platform:handle') / ('messenger', url) / ('website', host) or None."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host or any(s in host for s in _SKIP_SITES):
        return None
    if _MESSENGER_RE.match(url):
        # also on t.me itself: a channel description pointing at its owner
        return "messenger", url.split("?")[0].rstrip("/")
    if host == page_host:
        return None
    handle = handle_from_url(url)
    if handle:
        return "social", f"{host}/{handle}"
    if is_hub_domain(host):
        return None                          # a shop, news site or platform page, not "their site"
    return "website", host


class _Collector:
    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}

    def add(self, kind: str, value: str, page_url: str, how: str) -> None:
        value = value.strip()
        if not value:
            return
        key = (kind, value.casefold())
        entry = self.items.get(key)
        if entry is None:
            if sum(1 for k in self.items if k[0] == kind) >= MAX_PER_KIND:
                return
            entry = self.items[key] = {"kind": kind, "value": value, "how": how, "sources": []}
        if page_url and page_url not in entry["sources"] and len(entry["sources"]) < 3:
            entry["sources"].append(page_url)

    def result(self) -> list[dict]:
        order = {"email": 0, "phone": 1, "messenger": 2, "social": 3, "website": 4}
        return sorted(self.items.values(), key=lambda e: (order.get(e["kind"], 9), e["value"]))


# mail Message-IDs and UUIDs look like addresses: 20191218090054.GA5120@kroah.com
_MESSAGE_ID_RE = re.compile(r"\d{8,}|[0-9a-f]{12,}|^[0-9a-f]{8}-[0-9a-f]{4}-|_[0-9a-f]{5,}$", re.IGNORECASE)


_EXAMPLE_DOMAINS = {"example.com", "example.org", "example.net", "domain.com", "email.com", "mail.example"}


def _is_message_id(email: str) -> bool:
    local, _, domain = email.partition("@")
    return (bool(_MESSAGE_ID_RE.search(local)) or domain.endswith(".notmuch")
            or domain in _EXAMPLE_DOMAINS)       # documentation placeholders


def _collect_text(col: _Collector, text: str, page_url: str, page_host: str, how: str) -> None:
    # an address inside a URL is a path (mailing-list archive link), not a contact
    for email in emails_in(_URL_RE.sub(" ", text or "")):
        if not _is_message_id(email):
            col.add("email", email, page_url, how)
    for phone in phones_in(text):
        col.add("phone", phone, page_url, how)
    for url in _URL_RE.findall(text or ""):
        url = url.rstrip(".,;")
        if page_url and url.rstrip("/") == page_url.rstrip("/"):
            continue                            # the page linking to itself
        kind = _link_kind(url, page_host)
        if kind:
            col.add(kind[0], kind[1], page_url, how)


def contacts_from_text(text: str, page_url: str = "", how: str = "written in the profile text") -> list[dict]:
    """Contacts written in text that was already fetched (bio, description)."""
    col = _Collector()
    host = (urlparse(page_url).hostname or "").lower().removeprefix("www.")
    _collect_text(col, text, page_url, host, how)
    return col.result()


def contacts_from_html(html: str, page_url: str) -> tuple[list[dict], list[str]]:
    """(contacts on one page, same-site links worth reading next)."""
    col = _Collector()
    host = (urlparse(page_url).hostname or "").lower().removeprefix("www.")
    for raw in _MAILTO_RE.findall(html or ""):
        for email in emails_in(unescape(raw)):
            if not _is_message_id(email):
                col.add("email", email, page_url, "mailto link on the page")
    for raw in _TEL_RE.findall(html or ""):
        for phone in phones_in(unescape(raw)):
            col.add("phone", phone, page_url, "phone link on the page")
    _collect_text(col, _strip_html(html), page_url, host, "written on the page")

    contact_pages, other_pages = [], []
    for href, label in _HREF_RE.findall(html or ""):
        url = urljoin(page_url, unescape(href.strip())).split("#")[0]
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        link_host = (parsed.hostname or "").lower().removeprefix("www.")
        if link_host != host:
            kind = _link_kind(url, host)
            if kind:
                col.add(kind[0], kind[1], page_url, "linked from the page")
            continue
        haystack = (parsed.path + " " + re.sub(r"<[^>]+>", " ", label)).lower()
        bucket = contact_pages if any(w in haystack for w in CONTACT_WORDS) else other_pages
        if url not in bucket and url.rstrip("/") != page_url.rstrip("/"):
            bucket.append(url)
    # contact/about pages first, then whatever else the page links to
    return col.result(), contact_pages + other_pages


async def extract_contacts(url: str, max_pages: int = MAX_PAGES) -> dict:
    """Read a page and up to max_pages same-site pages it links to (1 level)."""
    start = url.strip()
    if not re.match(r"^https?://", start, re.IGNORECASE):
        start = "https://" + start
    if not urlparse(start).path:
        start += "/"                            # "https://site.uz" and ".../" are one page
    pages_read, notes = [], []
    merged = _Collector()
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT},
                                 follow_redirects=False) as client:
        robots = RobotFileParser()
        try:
            r = await safe_get(client, urljoin(start, "/robots.txt"), max_bytes=512 * 1024)
            if r.status_code >= 500:
                return {"url": start, "contacts": [], "pages": [],
                        "notes": ["robots.txt unavailable (server error): not reading the site"]}
            robots.parse(r.text.splitlines() if r.status_code == 200 else [])
        except UnsafeURLError as exc:
            return {"url": start, "contacts": [], "pages": [], "notes": [str(exc)]}
        except httpx.HTTPError as exc:
            return {"url": start, "contacts": [], "pages": [],
                    "notes": [f"site unreachable ({type(exc).__name__})"]}

        queue, seen = [start], set()
        depth_of = {start: 0}
        while queue and len(pages_read) < max_pages:
            page = queue.pop(0)
            if page in seen:
                continue
            seen.add(page)
            if not robots.can_fetch(USER_AGENT, page):
                notes.append(f"robots.txt disallows {urlparse(page).path or '/'}")
                continue
            if pages_read:
                await asyncio.sleep(PAUSE_SECONDS)
            try:
                response = await safe_get(client, page, max_bytes=MAX_BYTES)
            except (httpx.HTTPError, UnsafeURLError) as exc:
                notes.append(f"{page}: {type(exc).__name__}")
                continue
            if _looks_blocked(response):
                notes.append(f"stopped: {page} answered with a login wall or anti-bot check")
                break
            if response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
                continue
            pages_read.append(page)
            found, links = contacts_from_html(response.text, str(response.request.url))
            for item in found:
                for source in item["sources"]:
                    merged.add(item["kind"], item["value"], source, item["how"])
            if depth_of[page] == 0:
                for link in links:
                    if link not in depth_of:
                        depth_of[link] = 1
                        queue.append(link)
    return {"url": start, "contacts": merged.result(), "pages": pages_read, "notes": notes}
