import re

from tools.public_search import platform_from_url, search_public

SOCIAL_BATCHES = [
    "(site:linkedin.com/in OR site:x.com OR site:twitter.com OR site:instagram.com)",
    "(site:github.com OR site:tiktok.com OR site:youtube.com/@ "
    "OR site:medium.com/@ OR site:t.me OR site:reddit.com/user)",
    "(site:facebook.com OR site:pinterest.com OR site:threads.net "
    "OR site:vk.com OR site:ok.ru OR site:substack.com)",
]
PROFESSIONAL_BATCH = (
    "(site:wikipedia.org OR site:hh.uz OR site:hh.ru OR site:researchgate.net "
    "OR site:academia.edu OR site:scholar.google.com OR site:habr.com)"
)
NEWS_BATCH = (
    "(site:kun.uz OR site:daryo.uz OR site:gazeta.uz OR site:uza.uz "
    "OR site:qalampir.uz OR site:gov.uz)"
)
USERNAME_BATCHES = [
    "(site:instagram.com OR site:tiktok.com OR site:x.com OR site:facebook.com "
    "OR site:threads.net OR site:linkedin.com)",
    "(site:t.me OR site:reddit.com OR site:vk.com OR site:ok.ru "
    "OR site:pinterest.com OR site:youtube.com OR site:twitch.tv)",
    "(site:olx.uz OR site:github.com OR site:medium.com OR site:soundcloud.com "
    "OR site:spotify.com OR site:steamcommunity.com)",
]

LATIN_TO_CYRILLIC = [
    ("iyeva", "иева"), ("iyev", "иев"), ("yeva", "ева"), ("yev", "ев"),
    ("o'", "у"), ("g'", "г"), ("sh", "ш"), ("ch", "ч"), ("yo", "ё"),
    ("yu", "ю"), ("ya", "я"), ("ts", "ц"), ("a", "а"), ("b", "б"), ("d", "д"),
    ("e", "е"), ("f", "ф"), ("g", "г"), ("h", "х"), ("i", "и"), ("j", "ж"),
    ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"),
    ("q", "к"), ("r", "р"), ("s", "с"), ("t", "т"), ("u", "у"), ("v", "в"),
    ("w", "в"), ("x", "х"), ("y", "й"), ("z", "з"), ("c", "к"),
]
CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "",
    "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya", "ў": "o'", "қ": "q",
    "ғ": "g'", "ҳ": "h",
}
APOSTROPHES = re.compile("[ʻʼ’‘`]")


def _latin_word_to_cyrillic(word: str) -> str:
    word = APOSTROPHES.sub("'", word.casefold())
    # Web sources mostly use Russian-style spelling, e.g. Qodirov -> Кодиров.
    converted = "э" + word[1:] if word.startswith("e") else word
    for latin, cyrillic in LATIN_TO_CYRILLIC:
        converted = converted.replace(latin, cyrillic)
    return converted.replace("'", "").capitalize()


def transliterate(name: str) -> str | None:
    """Uzbek names appear in both scripts online; return the other spelling."""
    has_cyrillic = bool(re.search("[а-яёўқғҳ]", name.casefold()))
    if has_cyrillic:
        latin = "".join(CYRILLIC_TO_LATIN.get(c, c) for c in name.casefold())
        return latin.title().replace("'S", "'s") if latin.isascii() else None
    if not name.isascii() and not APOSTROPHES.search(name):
        return None
    return " ".join(_latin_word_to_cyrillic(word) for word in name.split())


def name_variants(name: str) -> list[str]:
    """Return spellings to search: as typed, family-name-first, other script."""
    variants = [name]
    words = name.split()
    if 2 <= len(words) <= 3:
        variants.append(" ".join([words[-1], *words[:-1]]))
    other_script = transliterate(name)
    if other_script:
        variants.append(other_script)
        other_words = other_script.split()
        if len(other_words) >= 2:
            variants.append(" ".join([other_words[-1], *other_words[:-1]]))
    return variants


def build_batches(variants: list[str]) -> list[str]:
    primary = f'"{variants[0]}"'
    batches = [f"{primary} {batch}" for batch in SOCIAL_BATCHES]
    batches += [f"{primary} {PROFESSIONAL_BATCH}", f"{primary} {NEWS_BATCH}"]
    for variant in variants[1:]:
        batches.append(f'"{variant}" {SOCIAL_BATCHES[0]}')
        batches.append(f'"{variant}" {NEWS_BATCH}')
    return batches


def _normalize(text: str) -> str:
    text = APOSTROPHES.sub("'", text.casefold())
    return re.sub(r"[\s_\-./]+", " ", text)


def classify_match(item: dict, variants: list[str]) -> str | None:
    """Rate how well a result names the person: exact, partial, or not at all."""
    text = _normalize(
        " ".join(str(item.get(key) or "") for key in ("title", "info", "url"))
    )
    normalized = [_normalize(variant) for variant in variants]
    if any(variant in text for variant in normalized):
        return "exact"
    if any(all(word in text for word in variant.split()) for variant in normalized):
        return "partial"
    return None


def filter_by_name(items: list[dict], variants: list[str]) -> tuple[list[dict], int]:
    kept = []
    for item in items:
        match = classify_match(item, variants)
        if match:
            kept.append({**item, "match": match})
    kept.sort(key=lambda item: item["match"] != "exact")
    return kept, len(items) - len(kept)


async def run_name_search(name: str) -> dict:
    variants = name_variants(name)
    results = await search_public(build_batches(variants), max_results_per_batch=10)
    kept, dropped = filter_by_name(results, variants)
    return {"tool": "name-search", "results": kept, "dropped": dropped, "variants": variants}


# Platforms whose public posts (reels, photos, captions) a search engine indexes
# even though the site walls the profile page behind a login.
SOCIAL_POST_SITES = [
    ("Instagram", "instagram.com"),
    ("TikTok", "tiktok.com"),
    ("Facebook", "facebook.com"),
    ("YouTube", "youtube.com"),
    ("X (Twitter)", "x.com"),
    ("Threads", "threads.net"),
    ("VK", "vk.com"),
]
HANDLE_RE = re.compile(r"@([A-Za-z0-9._](?:[A-Za-z0-9._]{1,28}[A-Za-z0-9_])?)")
MAX_TAGGED_HANDLES = 20


def extract_tagged_handles(text: str, subject: str) -> list[str]:
    """Pull @mentions out of a post caption; these are usually tagged friends."""
    subject_key = subject.casefold().lstrip("@")
    handles = []
    seen = set()
    for raw in HANDLE_RE.findall(text or ""):
        key = raw.casefold()
        if key == subject_key or key in seen or raw.endswith("."):
            continue
        seen.add(key)
        handles.append(raw)
    return handles[:MAX_TAGGED_HANDLES]


POST_PATH_RE = re.compile(
    r"/(p|reel|reels|tv|status|video|watch|posts|photo)/|/status/|[?&]v=",
    re.IGNORECASE,
)


def _is_post_url(url: str) -> bool:
    return bool(POST_PATH_RE.search(url or ""))


async def run_username_web(username: str) -> dict:
    """One sequential search pass covering both profiles and public posts.

    Kept as a single search_public call so the whole username investigation makes
    one rate-limited pass at DuckDuckGo instead of several that collide and all
    get throttled. Nothing is logged into - only indexed public pages are read.
    """
    handle = username.lstrip("@")
    quoted = f'"{handle}"'
    batches = [f"{quoted} {batch}" for batch in USERNAME_BATCHES]
    batches += [f"{quoted} site:{domain}" for _label, domain in SOCIAL_POST_SITES]
    results = await search_public(batches, max_results_per_batch=8)

    needle = handle.casefold()
    profiles = []
    posts = []
    tagged = []
    tagged_seen = set()
    profile_seen = set()
    post_seen = set()
    for item in results:
        url = item.get("url", "")
        caption = (item.get("info") or "").strip()
        haystack = f"{item.get('title','')} {caption} {url}"
        if needle not in haystack.casefold():
            continue
        key = url.split("#")[0].lower().rstrip("/")
        if _is_post_url(url):
            if key in post_seen:
                continue
            post_seen.add(key)
            post = {
                "platform": platform_from_url(url),
                "url": url,
                "status": "found",
                "kind": "post",
            }
            if item.get("title"):
                post["title"] = item["title"]
            if caption:
                post["info"] = caption
            posts.append(post)
            for found in extract_tagged_handles(f"{item.get('title','')} {caption}", handle):
                if found.casefold() not in tagged_seen:
                    tagged_seen.add(found.casefold())
                    tagged.append(found)
        else:
            if key in profile_seen:
                continue
            profile_seen.add(key)
            profiles.append(item)

    pivots = [{"type": "username", "value": h} for h in tagged[:MAX_TAGGED_HANDLES]]
    return {
        "tool": "username-web",
        "results": profiles,
        "posts": posts,
        "pivots": pivots,
    }
