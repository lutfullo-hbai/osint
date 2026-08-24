import re
import shutil
import sys

from tools.base import ToolError, run_command, shorten, strip_ansi

SHERLOCK_TIMEOUT_SECONDS = 300

FOUND_LINE_RE = re.compile(r"^\[\+\]\s*(?P<platform>[^:\s][^:]*?)\s*:\s*(?P<url>\S+)\s*$")


def parse_found(stdout: str) -> list[dict]:
    results = []
    seen = set()
    for line in strip_ansi(stdout).splitlines():
        match = FOUND_LINE_RE.match(line.strip())
        if not match:
            continue
        platform = match.group("platform").strip()
        url = match.group("url").strip()
        if not platform or not re.match(r"^https?://", url):
            continue
        key = (platform.lower(), url.lower())
        if key in seen:
            continue
        seen.add(key)
        results.append({"platform": platform, "url": url, "status": "found"})
    return results


def _build_command(username: str) -> list[str]:
    sherlock_binary = shutil.which("sherlock")
    if sherlock_binary:
        base = [sherlock_binary]
    elif shutil.which("python3"):
        base = ["python3", "-m", "sherlock_project"]
    else:
        base = [sys.executable, "-m", "sherlock_project"]
    return [
        *base,
        username,
        "--timeout",
        "15",
        "--no-color",
        "--no-txt",
        "--print-found",
    ]


async def run_sherlock(username: str) -> dict:
    execution = await run_command(_build_command(username), timeout=SHERLOCK_TIMEOUT_SECONDS)
    results = parse_found(execution["stdout"]) or parse_found(execution["stderr"])
    if execution["returncode"] != 0 and not results:
        raise ToolError(
            f"Sherlock exited with code {execution['returncode']}: "
            f"{shorten(execution['stderr'])}"
        )
    return {"tool": "sherlock", "results": results}
