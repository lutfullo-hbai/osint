"""Structured lookups against data platforms publish without a login.

Only official APIs and public preview pages are used, under an honest User-Agent.
Platforms that require a login or refuse automated clients (Instagram, TikTok,
X, Facebook, Reddit, Wikimedia) are not fetched here: they are covered through
search-engine indexes and manual-check links. Do not work around those blocks.
"""
import asyncio
import html
import re
from urllib.parse import quote, urlparse

import httpx

from tools.base import ToolError
from tools.domain_intel import DomainValidationError, normalize_domain

HEADERS = {"User-Agent": "osint-tool/1.0 (+self-hosted research tool)"}
TIMEOUT = httpx.Timeout(12.0)
TELEGRAM_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
MAX_NAME_MATCHES = 5


def _epoch_to_date(value) -> str:
    import datetime
    if not isinstance(value, (int, float)):
        return ""
    try:
        return datetime.datetime.fromtimestamp(
            value, tz=datetime.timezone.utc
        ).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        return ""

LOGIN_WALLED_PROFILES = {
    "Instagram": "https://www.instagram.com/{u}/",
    "TikTok": "https://www.tiktok.com/@{u}",
    "X (Twitter)": "https://x.com/{u}",
    "Facebook": "https://www.facebook.com/{u}",
    "Threads": "https://www.threads.net/@{u}",
    "LinkedIn": "https://www.linkedin.com/in/{u}",
    "Reddit": "https://www.reddit.com/user/{u}",
}


def manual_links(username: str) -> list[dict]:
    return [
        {"label": label, "url": template.format(u=username)}
        for label, template in LOGIN_WALLED_PROFILES.items()
    ]


def _entry(platform: str, url: str, fields: list[tuple[str, object]], **extra) -> dict:
    parts = [f"{label}: {value}" for label, value in fields if value not in (None, "")]
    return {
        "platform": platform,
        "url": url,
        "status": "found",
        "info": "; ".join(parts) or "Public profile exists.",
        **extra,
    }


async def fetch_json(client: httpx.AsyncClient, url: str, missing=(404,), **kwargs):
    response = await client.get(url, **kwargs)
    if response.status_code in missing:
        return None
    if response.status_code == 429:
        raise ToolError("rate limit reached.")
    if response.status_code != 200:
        raise ToolError(f"HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        raise ToolError("malformed JSON.") from exc


def parse_telegram(page: str, username: str) -> dict | None:
    # t.me serves a generic "Contact @x" page for unknown names, without this block.
    if "tgme_page_title" not in page:
        return None

    def meta(prop: str) -> str:
        match = re.search(rf'<meta property="{prop}" content="([^"]*)"', page)
        return html.unescape(match.group(1)).strip() if match else ""

    # For accounts with no bio Telegram fills these with boilerplate.
    bio = meta("og:description")
    if bio.startswith("You can contact @"):
        bio = ""
    extra = re.search(r'tgme_page_extra">\s*([^<]+?)\s*<', page)
    audience = html.unescape(extra.group(1)) if extra else ""
    if audience.startswith("@"):
        audience = ""
    return _entry(
        "Telegram",
        f"https://t.me/{username}",
        [
            ("Name", meta("og:title")),
            ("Bio", bio),
            ("Audience", audience),
        ],
    )


async def telegram_profile(client, username):
    if not TELEGRAM_USERNAME_RE.fullmatch(username):
        return None
    response = await client.get(f"https://t.me/{username}")
    if response.status_code != 200:
        raise ToolError(f"HTTP {response.status_code}.")
    return parse_telegram(response.text, username)


def parse_github(data: dict) -> dict:
    return _entry(
        "GitHub",
        data.get("html_url", ""),
        [
            ("Name", data.get("name")),
            ("Bio", data.get("bio")),
            ("Company", data.get("company")),
            ("Location", data.get("location")),
            ("Website", data.get("blog")),
            ("Repos", data.get("public_repos")),
            ("Followers", data.get("followers")),
            ("Joined", str(data.get("created_at") or "")[:10]),
        ],
        website=data.get("blog") or "",
        linked_username=data.get("twitter_username") or "",
    )


async def github_profile(client, username):
    data = await fetch_json(client, f"https://api.github.com/users/{username}")
    return parse_github(data) if data else None


async def gitlab_profile(client, username):
    users = await fetch_json(
        client, f"https://gitlab.com/api/v4/users?username={quote(username)}"
    )
    if not users:
        return None
    user = users[0]
    return _entry(
        "GitLab",
        user.get("web_url", ""),
        [("Name", user.get("name")), ("State", user.get("state"))],
    )


async def hackernews_profile(client, username):
    data = await fetch_json(
        client, f"https://hacker-news.firebaseio.com/v0/user/{username}.json"
    )
    if not data:
        return None
    return _entry(
        "Hacker News",
        f"https://news.ycombinator.com/user?id={username}",
        [("Karma", data.get("karma")), ("About", re.sub(r"<[^>]+>", " ", data.get("about") or "")[:200])],
    )


async def keybase_profile(client, username):
    data = await fetch_json(
        client, f"https://keybase.io/_/api/1.0/user/lookup.json?usernames={username}"
    )
    them = ((data or {}).get("them") or [None])[0]
    if not them:
        return None
    profile = them.get("profile") or {}
    proofs = ((them.get("proofs_summary") or {}).get("all")) or []
    return _entry(
        "Keybase",
        f"https://keybase.io/{username}",
        [
            ("Name", profile.get("full_name")),
            ("Bio", profile.get("bio")),
            ("Location", profile.get("location")),
            (
                "Verified identities",
                ", ".join(
                    f"{proof.get('proof_type')}:{proof.get('nametag')}"
                    for proof in proofs[:8]
                ),
            ),
        ],
    )


async def devto_profile(client, username):
    data = await fetch_json(
        client, f"https://dev.to/api/users/by_username?url={username}"
    )
    if not data:
        return None
    return _entry(
        "DEV Community",
        f"https://dev.to/{username}",
        [
            ("Name", data.get("name")),
            ("Bio", data.get("summary")),
            ("Location", data.get("location")),
            ("Website", data.get("website_url")),
        ],
        website=data.get("website_url") or "",
    )


async def bluesky_profile(client, username):
    data = await fetch_json(
        client,
        "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile"
        f"?actor={username}.bsky.social",
        missing=(400, 404),
    )
    if not data:
        return None
    return _entry(
        "Bluesky",
        f"https://bsky.app/profile/{data.get('handle', '')}",
        [
            ("Name", data.get("displayName")),
            ("Bio", data.get("description")),
            ("Followers", data.get("followersCount")),
        ],
    )


async def mastodon_profile(client, username):
    data = await fetch_json(
        client, f"https://mastodon.social/api/v1/accounts/lookup?acct={username}"
    )
    if not data:
        return None
    return _entry(
        "Mastodon",
        data.get("url", ""),
        [
            ("Name", data.get("display_name")),
            ("Bio", re.sub(r"<[^>]+>", " ", data.get("note") or "").strip()[:200]),
            ("Followers", data.get("followers_count")),
        ],
    )


async def dockerhub_profile(client, username):
    data = await fetch_json(client, f"https://hub.docker.com/v2/users/{username}")
    if not data:
        return None
    return _entry(
        "Docker Hub",
        f"https://hub.docker.com/u/{username}",
        [
            ("Name", data.get("full_name")),
            ("Company", data.get("company")),
            ("Location", data.get("location")),
        ],
    )


async def lichess_profile(client, username):
    data = await fetch_json(client, f"https://lichess.org/api/user/{username}")
    if not data or data.get("disabled"):
        return None
    profile = data.get("profile") or {}
    return _entry(
        "Lichess",
        data.get("url", ""),
        [("Bio", profile.get("bio")), ("Games", (data.get("count") or {}).get("all"))],
    )


async def codeforces_profile(client, username):
    data = await fetch_json(
        client,
        f"https://codeforces.com/api/user.info?handles={username}",
        missing=(400, 404),
    )
    users = (data or {}).get("result") or []
    if not users:
        return None
    user = users[0]
    return _entry(
        "Codeforces",
        f"https://codeforces.com/profile/{username}",
        [
            ("Rank", user.get("rank")),
            ("Rating", user.get("rating")),
            ("Organization", user.get("organization")),
            ("Country", user.get("country")),
        ],
    )


async def chesscom_profile(client, username):
    data = await fetch_json(client, f"https://api.chess.com/pub/player/{username}")
    if not data or data.get("status") == "closed:fair_play_violations":
        return None
    return _entry(
        "Chess.com",
        data.get("url", ""),
        [
            ("Name", data.get("name")),
            ("Location", data.get("location")),
            ("Followers", data.get("followers")),
            ("Joined", _epoch_to_date(data.get("joined"))),
        ],
    )


async def npm_profile(client, username):
    data = await fetch_json(
        client,
        f"https://registry.npmjs.org/-/v1/search?text=author:{quote(username)}&size=5",
    )
    packages = (data or {}).get("objects") or []
    if not packages:
        return None
    names = [pkg.get("package", {}).get("name", "") for pkg in packages]
    return _entry(
        "npm",
        f"https://www.npmjs.com/~{username}",
        [("Packages", ", ".join(n for n in names if n)[:200])],
    )


async def gravatar_username(client, username):
    data = await fetch_json(client, f"https://gravatar.com/{username}.json")
    try:
        entry = data["entry"][0]
    except (TypeError, KeyError, IndexError):
        return None
    fields = []
    for label, key in (("Name", "displayName"), ("Location", "currentLocation"),
                       ("Job", "job_title"), ("Company", "company")):
        if entry.get(key):
            fields.append((label, entry[key]))
    accounts = entry.get("accounts") or []
    linked = ""
    if accounts:
        fields.append(("Linked", ", ".join(
            f"{a.get('shortname')}:{a.get('username')}" for a in accounts[:6]
        )))
        for account in accounts:
            if str(account.get("shortname")).lower() in GITHUB_LIKE and account.get("username"):
                linked = account["username"]
                break
    return _entry(
        "Gravatar",
        entry.get("profileUrl", f"https://gravatar.com/{username}"),
        fields,
        linked_username=linked,
    )


GITHUB_LIKE = {"github", "twitter", "instagram", "tiktok"}

PROFILE_SOURCES = {
    "Chess.com": chesscom_profile,
    "npm": npm_profile,
    "Gravatar": gravatar_username,
    "Telegram": telegram_profile,
    "GitHub": github_profile,
    "GitLab": gitlab_profile,
    "Hacker News": hackernews_profile,
    "Keybase": keybase_profile,
    "DEV Community": devto_profile,
    "Bluesky": bluesky_profile,
    "Mastodon": mastodon_profile,
    "Docker Hub": dockerhub_profile,
    "Lichess": lichess_profile,
    "Codeforces": codeforces_profile,
}


async def _gather(lookups: dict) -> tuple[list[dict], list[str]]:
    outcomes = await asyncio.gather(*lookups.values(), return_exceptions=True)
    entries: list[dict] = []
    warnings: list[str] = []
    for label, outcome in zip(lookups, outcomes):
        if isinstance(outcome, ToolError):
            warnings.append(f"{label}: {outcome}")
        elif isinstance(outcome, BaseException):
            warnings.append(f"{label}: {type(outcome).__name__}")
        elif isinstance(outcome, list):
            entries.extend(outcome)
        elif outcome:
            entries.append(outcome)
    return entries, warnings


def extract_pivots(entries: list[dict]) -> list[dict]:
    """Pop pivot hints off entries so they don't leak into the rendered result."""
    pivots = []
    seen = set()

    def add(kind: str, value: str):
        if (kind, value.lower()) not in seen:
            seen.add((kind, value.lower()))
            pivots.append({"type": kind, "value": value})

    for entry in entries:
        website = entry.pop("website", "")
        if website:
            host = urlparse(website if "//" in website else f"//{website}").hostname
            try:
                add("domain", normalize_domain(host or ""))
            except DomainValidationError:
                pass
        linked = entry.pop("linked_username", "")
        if linked:
            add("username", linked)
    return pivots


async def run_profile_sources(username: str) -> dict:
    async with httpx.AsyncClient(
        headers=HEADERS, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        entries, warnings = await _gather(
            {label: fetch(client, username) for label, fetch in PROFILE_SOURCES.items()}
        )
    pivots = extract_pivots(entries)
    return {"results": entries, "warnings": warnings, "pivots": pivots}


async def orcid_search(client, name: str) -> list[dict]:
    data = await fetch_json(
        client,
        "https://pub.orcid.org/v3.0/expanded-search/",
        params={"q": f'given-and-family-names:"{name}"', "rows": MAX_NAME_MATCHES},
        headers={"Accept": "application/json"},
    )
    rows = (data or {}).get("expanded-result") or []
    return [
        _entry(
            "ORCID",
            f"https://orcid.org/{row.get('orcid-id')}",
            [("Institutions", ", ".join((row.get("institution-name") or [])[:3]))],
            title=f"{row.get('given-names', '')} {row.get('family-names', '')}".strip(),
        )
        for row in rows
    ]


async def openalex_search(client, name: str) -> list[dict]:
    data = await fetch_json(
        client,
        "https://api.openalex.org/authors",
        params={"search": name, "per-page": MAX_NAME_MATCHES},
    )
    entries = []
    for author in (data or {}).get("results") or []:
        institutions = author.get("last_known_institutions") or []
        entries.append(
            _entry(
                "OpenAlex",
                author.get("id", ""),
                [
                    ("Institution", institutions[0].get("display_name") if institutions else ""),
                    ("Works", author.get("works_count")),
                ],
                title=author.get("display_name", ""),
            )
        )
    return entries


async def github_name_search(client, name: str) -> list[dict]:
    data = await fetch_json(
        client,
        "https://api.github.com/search/users",
        params={"q": f'"{name}" in:name', "per_page": MAX_NAME_MATCHES},
    )
    return [
        {
            "platform": "GitHub",
            "url": item.get("html_url", ""),
            "status": "found",
            "title": item.get("login", ""),
            "info": "Account whose display name matches.",
            "linked_username": item.get("login", ""),
        }
        for item in (data or {}).get("items") or []
    ]


async def run_name_sources(name: str) -> dict:
    async with httpx.AsyncClient(
        headers=HEADERS, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        entries, warnings = await _gather(
            {
                "ORCID": orcid_search(client, name),
                "OpenAlex": openalex_search(client, name),
                "GitHub search": github_name_search(client, name),
            }
        )
    pivots = extract_pivots(entries)
    return {"results": entries, "warnings": warnings, "pivots": pivots}
