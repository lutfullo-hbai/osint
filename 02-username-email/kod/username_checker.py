import sys
import requests

SITES = {
    "GitHub": "https://github.com/{username}",
    "Telegram": "https://t.me/{username}",
    "Instagram": "https://www.instagram.com/{username}/",
    "X (Twitter)": "https://x.com/{username}",
    "Reddit": "https://www.reddit.com/user/{username}/",
    "Pinterest": "https://www.pinterest.com/{username}/",
    "GitLab": "https://gitlab.com/{username}",
    "Steam": "https://steamcommunity.com/id/{username}/",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def check_site(name: str, url: str) -> str:
    try:
        response = requests.get(url.format(username=""), headers=HEADERS, timeout=8)
        empty_status = response.status_code
        response = requests.get(
            url.format(username=TARGET), headers=HEADERS, timeout=8
        )
        if response.status_code == 200 and empty_status != 200:
            return "TOPILDI"
        if response.status_code == 200 and empty_status == 200:
            return "NOANIQ (sayt har doim 200 qaytaradi)"
        return f"YO'Q ({response.status_code})"
    except requests.RequestException as error:
        return f"XATO ({type(error).__name__})"


def main():
    global TARGET
    if len(sys.argv) != 2:
        print(f"Xato: python3 {sys.argv[0]} <username>")
        sys.exit(1)

    TARGET = sys.argv[1]
    print(f"[i] '{TARGET}' tekshirilmoqda...\n")

    for name, url in SITES.items():
        result = check_site(name, url)
        icon = "+" if result.startswith("TOPILDI") else "-"
        print(f"[{icon}] {name}: {result}")


if __name__ == "__main__":
    main()
