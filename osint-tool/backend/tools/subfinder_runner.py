"""Subfinder (ProjectDiscovery, MIT): passive subdomain enumeration.

It queries dozens of passive sources (certificate logs, DNS datasets, web
archives) without touching the target. Sources that need API keys are skipped
unless a provider config is present, so it works key-free out of the box.
"""
import json
import re
import shutil

from tools.base import ToolError, positional_arg, run_command, shorten

SUBFINDER_TIMEOUT_SECONDS = 150
# a few domains (example.com) have tens of thousands of junk names in passive
# datasets; keep the result bounded
MAX_HOSTS = 5000
# per-source timeout and total enumeration budget handed to subfinder itself
SOURCE_TIMEOUT_SECONDS = 20
MAX_TIME_MINUTES = 2

_HOST_RE = re.compile(r"^[a-z0-9*_.-]+$")


def parse_jsonl(stdout: str, domain: str) -> tuple[set[str], set[str]]:
    """JSONL lines -> (hosts under the domain, sources that produced them)."""
    hosts, sources = set(), set()
    suffix = "." + domain.lower()
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        host = str(row.get("host") or "").strip().lower().lstrip("*.").rstrip(".")
        if not host or not _HOST_RE.match(host):
            continue
        if host == domain.lower() or host.endswith(suffix):
            hosts.add(host)
            for src in row.get("sources") or ([row["source"]] if row.get("source") else []):
                sources.add(str(src))
    return hosts, sources


async def run_subfinder(domain: str) -> set[str]:
    if shutil.which("subfinder") is None:
        raise ToolError("skipped (subfinder binary not installed)")
    command = [
        "subfinder",
        "-silent",
        "-json",
        "-cs",  # list every source that saw a host
        "-timeout", str(SOURCE_TIMEOUT_SECONDS),
        "-max-time", str(MAX_TIME_MINUTES),
        "-disable-update-check",
        "-d", positional_arg(domain),
    ]
    execution = await run_command(command, timeout=SUBFINDER_TIMEOUT_SECONDS)
    hosts, _sources = parse_jsonl(execution["stdout"], domain)
    if execution["returncode"] != 0 and not hosts:
        raise ToolError(
            f"subfinder exited with code {execution['returncode']}: "
            f"{shorten(execution['stderr']) or 'no output'}"
        )
    return set(sorted(hosts)[:MAX_HOSTS])
