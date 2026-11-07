import json
import re
import sys
import time

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

SITES = {
    "GitHub": {
        "url": "https://github.com/{username}",
        "not_found": ["page not found"],
    },
    "GitLab": {
        "url": "https://gitlab.com/{username}",
        "not_found": ["page not found"],
    },
    "Reddit": {
        "url": "https://www.reddit.com/user/{username}/",
        "not_found": ["nobody on reddit goes by that name"],
    },
    "Hacker News": {
        "url": "https://news.ycombinator.com/user?id={username}",
        "not_found": ["no such user"],
    },
    "Steam": {
        "url": "https://steamcommunity.com/id/{username}",
        "not_found": ["the specified profile could not be found"],
    },
    "Keybase": {
        "url": "https://keybase.io/{username}",
        "not_found": ["page not found"],
    },
    "SoundCloud": {
        "url": "https://soundcloud.com/{username}",
        "not_found": ["we can't find that page"],
    },
    "Dribbble": {
        "url": "https://dribbble.com/{username}",
        "not_found": ["page not found"],
    },
    "DEV Community": {
        "url": "https://dev.to/{username}",
        "not_found": ["page not found"],
    },
}

BLOCK_MARKERS = [
    "checking your browser",
    "verify you are human",
    "too many requests",
    "rate limit exceeded",
    "enable javascript and cookies to continue",
    "access denied",
]

MANUAL_LINKS = {
    "Telegram": "https://t.me/{username}",
    "Instagram": "https://www.instagram.com/{username}/",
    "X (Twitter)": "https://x.com/{username}",
    "Facebook": "https://www.facebook.com/{username}",
    "TikTok": "https://www.tiktok.com/@{username}",
    "LinkedIn": "https://www.linkedin.com/in/{username}/",
}

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,32}$")


def classify(response: requests.Response, not_found: list[str]) -> tuple[str, int]:
    if response.status_code in (404, 410):
        return "YO'Q", response.status_code

    text = response.text.lower()
    if any(marker in text for marker in not_found):
        return "YO'Q", response.status_code
    if any(marker in text for marker in BLOCK_MARKERS):
        return "NOANIQ (blok/captcha)", response.status_code
    if 200 <= response.status_code < 300:
        return "TOPILDI", response.status_code
    return f"NOANIQ (HTTP {response.status_code})", response.status_code


def check_site(name: str, config: dict, username: str) -> dict:
    url = config["url"].format(username=username)
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=10,
            allow_redirects=True,
        )
    except requests.RequestException as error:
        return {"platform": name, "url": url, "status": f"XATO ({type(error).__name__})"}

    status, code = classify(response, config.get("not_found", []))
    return {"platform": name, "url": url, "status": status, "http_status": code}


def main() -> None:
    args = [arg for arg in sys.argv[1:] if arg != "--json"]
    if len(args) != 1:
        print(f"Foydalanish: python3 {sys.argv[0]} <username> [--json natija.json]")
        sys.exit(1)

    username = args[0].strip().lstrip("@")
    if not USERNAME_RE.match(username):
        print("[XATO] Username 2-32 belgi: harflar, raqamlar, . _ - bo'lishi kerak.")
        sys.exit(1)

    print(f"[i] '{username}' ochiq platformalarda tekshirilmoqda...\n")
    results = []
    for name, config in SITES.items():
        result = check_site(name, config, username)
        results.append(result)
        print(f"  {name:<14} {result['status']}  {result['url']}")
        time.sleep(0.5)

    found = sum(1 for item in results if item["status"] == "TOPILDI")
    missing = sum(1 for item in results if item["status"] == "YO'Q")
    print(f"\n[i] Topildi: {found} | Yo'q: {missing} | Boshqa: {len(results) - found - missing}")

    print("\n[i] Qo'lda tekshirish (login talab qilishi mumkin):")
    for name, url in MANUAL_LINKS.items():
        print(f"  {name}: {url.format(username=username)}")

    if "--json" in sys.argv:
        path = sys.argv[sys.argv.index("--json") + 1]
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {"username": username, "results": results},
                handle,
                ensure_ascii=False,
                indent=2,
            )
        print(f"\n[i] Natija saqlandi: {path}")

    print("\n[!] Natijalar — gipoteza. Har birini brauzerda qo'lda tasdiqlang.")


if __name__ == "__main__":
    main()
