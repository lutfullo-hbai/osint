import re

from tools.base import ToolError, run_command, shorten, strip_ansi

HOLEHE_TIMEOUT_SECONDS = 300

FOUND_LINE_RE = re.compile(
    r"^\[\+\]\s*(?P<domain>[A-Za-z0-9.-]+\.[A-Za-z]{2,})\s*(?P<info>.*)$"
)


def parse_found(stdout: str) -> list[dict]:
    results = []
    seen = set()
    for raw_line in strip_ansi(stdout).splitlines():
        match = FOUND_LINE_RE.match(raw_line.strip())
        if not match:
            continue
        domain = match.group("domain").strip().lower()
        info = match.group("info").strip()
        if domain in seen:
            continue
        seen.add(domain)
        entry = {
            "platform": domain,
            "url": f"https://{domain}",
            "status": "registered",
        }
        if info:
            entry["info"] = info
        results.append(entry)
    return results


async def run_holehe(email: str) -> dict:
    command = [
        "holehe",
        email,
        "--only-used",
        "--no-color",
    ]
    execution = await run_command(command, timeout=HOLEHE_TIMEOUT_SECONDS)
    results = parse_found(execution["stdout"])
    if execution["returncode"] != 0 and not results:
        raise ToolError(
            f"Holehe exited with code {execution['returncode']}: "
            f"{shorten(execution['stderr'])}"
        )
    return {"tool": "holehe", "results": results}
