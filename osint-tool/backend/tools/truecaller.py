import re

import httpx

SEARCH_URL_TEMPLATE = "https://www.truecaller.com/search/{region}/{number}"

REGION_BY_CALLING_CODE = [
    ("+91", "in"),
    ("+1", "us"),
    ("+44", "gb"),
    ("+234", "ng"),
    ("+62", "id"),
    ("+971", "ae"),
    ("+46", "se"),
]

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

META_CONTENT_RE = re.compile(
    r'<meta[^>]+(?:property|name)="og:(?:title|description)"[^>]+content="([^"]+)"',
    re.IGNORECASE,
)
FULL_NAME_RE = re.compile(r'"(?:fullName|displayName)"\s*:\s*"([^"]{2,80})"')
NAME_NEAR_PHONE_RE = re.compile(
    r'"name"\s*:\s*"([A-Za-z .\'\-]{3,60})"\s*,[^{}]{0,200}"phoneNumber"',
)
ADDRESS_RE = re.compile(r'"(?:address|city|country|carrier)"\s*:\s*"([^"]{2,80})"')
BLOCK_MARKERS = (
    "captcha",
    "access denied",
    "verify you are",
    "are you a robot",
)

GENERIC_NAME_TOKENS = {
    "truecaller",
    "caller id",
    "phone number",
    "spam lookup",
    "search",
}


class TruecallerUnavailable(Exception):
    pass


def pick_region(number: str) -> str:
    normalized = number.replace(" ", "")
    for prefix, region in REGION_BY_CALLING_CODE:
        if normalized.startswith(prefix):
            return region
    return "in"


def _plausible_name(candidate: str | None) -> str | None:
    if not candidate:
        return None
    name = candidate.strip()
    lowered = name.lower()
    if len(name) < 2 or len(name) > 80:
        return None
    if any(marker in lowered for marker in BLOCK_MARKERS):
        return None
    if any(token == lowered for token in GENERIC_NAME_TOKENS):
        return None
    if not re.search(r"[A-Za-z]", name):
        return None
    return name


def _extract_from_html(html: str) -> dict:
    name = None
    info_parts = []

    full_name_match = FULL_NAME_RE.search(html)
    if full_name_match:
        name = _plausible_name(full_name_match.group(1))

    if not name:
        for near_match in NAME_NEAR_PHONE_RE.finditer(html):
            name = _plausible_name(near_match.group(1))
            if name:
                break

    seen_info = set()
    for match in ADDRESS_RE.finditer(html):
        value = match.group(1).strip()
        key = value.lower()
        if value and key not in seen_info and _plausible_name(value):
            seen_info.add(key)
            info_parts.append(value)
    if not info_parts:
        for meta_match in META_CONTENT_RE.finditer(html):
            value = meta_match.group(1).strip()
            key = value.lower()
            if value and key not in seen_info:
                seen_info.add(key)
                info_parts.append(value)

    return {
        "name": name,
        "info": "; ".join(info_parts[:6]) if info_parts else "",
    }


async def scrape_truecaller(number: str, region: str) -> dict:
    url = SEARCH_URL_TEMPLATE.format(region=region, number=number.lstrip("+"))
    try:
        async with httpx.AsyncClient(
            headers=BROWSER_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(30.0),
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise TruecallerUnavailable(
            f"Could not reach Truecaller ({type(exc).__name__}: {exc or 'connection failed'}). "
            "Check network connectivity."
        ) from exc

    if response.status_code in (401, 403, 429):
        raise TruecallerUnavailable(
            f"Truecaller refused the request (HTTP {response.status_code}). "
            "Full details usually require a logged-in session."
        )
    if response.status_code != 200:
        raise TruecallerUnavailable(
            f"Truecaller returned unexpected HTTP {response.status_code}."
        )

    html = response.text
    lowered_head = html[:4000].lower()
    if any(marker in lowered_head for marker in BLOCK_MARKERS):
        raise TruecallerUnavailable(
            "Truecaller served an anti-bot challenge instead of search results."
        )

    extracted = _extract_from_html(html)
    return {"profile_url": url, **extracted}
