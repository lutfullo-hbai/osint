"""Shared-platform domains: hosts that thousands of unrelated people use.

A personal website on github.io or a "Website: linkedin.com/in/x" field says
nothing about the domain's owner, and two strangers who both list a LinkedIn
URL must not be tied together through linkedin.com. Such hosts never become
domain pivots.
"""

HUB_DOMAINS = frozenset({
    # social / profile hosts
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "t.me", "telegram.me", "tiktok.com", "youtube.com", "youtu.be", "vk.com",
    "ok.ru", "reddit.com", "medium.com", "substack.com", "pinterest.com",
    "threads.net", "bsky.app", "mastodon.social", "discord.gg", "discord.com",
    # link-in-bio and profile pages
    "linktr.ee", "about.me", "beacons.ai", "bio.link", "carrd.co",
    "taplink.cc", "gravatar.com", "keybase.io",
    # code and free hosting
    "github.com", "github.io", "gitlab.com", "gitlab.io", "bitbucket.org",
    "netlify.app", "vercel.app", "pages.dev", "herokuapp.com", "web.app",
    "firebaseapp.com", "blogspot.com", "wordpress.com", "wixsite.com",
    "tilda.ws", "notion.site", "google.com", "sites.google.com",
    "ucoz.ru", "narod.ru",
    # free mailbox providers
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "live.com", "icloud.com", "me.com", "proton.me", "protonmail.com",
    "mail.ru", "inbox.ru", "list.ru", "bk.ru", "yandex.ru", "yandex.com",
    "ya.ru", "rambler.ru", "gmx.com", "gmx.de", "aol.com", "zoho.com",
})


def is_hub_domain(host: str) -> bool:
    """True for a shared platform host or any subdomain of one."""
    host = str(host or "").strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    return any(".".join(parts[i:]) in HUB_DOMAINS for i in range(len(parts) - 1))
