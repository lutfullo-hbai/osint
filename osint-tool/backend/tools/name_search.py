import re

from tools.base import ToolError
from tools.public_search import search_public

QUERY_BATCHES = [
    "(site:linkedin.com/in OR site:x.com OR site:twitter.com OR site:instagram.com)",
    "(site:github.com OR site:tiktok.com OR site:youtube.com/@ "
    "OR site:medium.com/@ OR site:t.me OR site:reddit.com/user)",
    "(site:facebook.com OR site:pinterest.com OR site:threads.net "
    "OR site:vk.com OR site:ok.ru OR site:substack.com)",
]


def _build_batches(name: str) -> list[str]:
    quoted = f'"{name}"'
    return [f"{quoted} {batch}" for batch in QUERY_BATCHES]


async def run_name_search(name: str) -> dict:
    results = await search_public(_build_batches(name))
    return {"tool": "name-search", "results": results}
