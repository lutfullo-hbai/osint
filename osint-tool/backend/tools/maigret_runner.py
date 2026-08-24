import glob
import json
import os
import tempfile

from tools.base import ToolError, run_command, shorten, strip_ansi

MAIGRET_TIMEOUT_SECONDS = 900
FOUND_STATUSES = {"claimed", "found"}


def _extract_json_payloads(text: str) -> list:
    stripped = strip_ansi(text).strip()
    if not stripped:
        return []

    try:
        parsed = json.loads(stripped)
        return [parsed] if isinstance(parsed, (dict, list)) else []
    except json.JSONDecodeError:
        pass

    payloads = []
    for line in stripped.splitlines():
        candidate = line.strip()
        if not candidate.startswith("{") and not candidate.startswith("["):
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, (dict, list)):
                payloads.append(parsed)
        except json.JSONDecodeError:
            continue

    if payloads:
        return payloads

    starts = [i for i in (stripped.find("{"), stripped.find("[")) if i != -1]
    if not starts:
        return []
    start = min(starts)
    end = max(stripped.rfind("}"), stripped.rfind("]"))
    if end <= start:
        return []
    try:
        parsed = json.loads(stripped[start : end + 1])
        return [parsed] if isinstance(parsed, (dict, list)) else []
    except json.JSONDecodeError:
        return []


def _status_of(entry: dict) -> str:
    status_field = entry.get("status")
    if isinstance(status_field, dict):
        return str(status_field.get("status", "")).strip().lower()
    if isinstance(status_field, str):
        return status_field.strip().lower()
    return ""


def _entry_to_result(sitename: str, entry: dict) -> dict | None:
    status = _status_of(entry)
    if status not in FOUND_STATUSES:
        return None

    status_info = entry.get("status") if isinstance(entry.get("status"), dict) else {}
    site = entry.get("site") if isinstance(entry.get("site"), dict) else {}

    platform = (
        status_info.get("site_name")
        or site.get("siteName")
        or site.get("name")
        or sitename
        or "Unknown"
    )
    url = (
        status_info.get("url")
        or entry.get("url")
        or site.get("siteUrlUser")
        or site.get("url_user")
        or ""
    )

    result = {
        "platform": str(platform).strip(),
        "url": str(url).strip(),
        "status": "found",
    }

    info_bits = []
    tags = entry.get("tags") or site.get("tags") or []
    if isinstance(tags, list) and tags:
        info_bits.append("tags: " + ", ".join(str(tag) for tag in tags[:5]))
    ids_data = entry.get("ids")
    if isinstance(ids_data, dict) and ids_data:
        extracted_ids = [
            f"{key}: {value}" for key, value in list(ids_data.items())[:3]
        ]
        info_bits.append("; ".join(extracted_ids))
    if info_bits:
        result["info"] = "; ".join(info_bits)

    return result


def parse_payload(payload) -> list[dict]:
    results = []
    seen = set()
    items = []
    if isinstance(payload, dict):
        items.extend(payload.items())
    elif isinstance(payload, list):
        items.extend((str(index), item) for index, item in enumerate(payload))

    for sitename, item in items:
        if not isinstance(item, dict):
            continue
        result = _entry_to_result(str(sitename), item)
        if result is None:
            continue
        key = (result["platform"].lower(), result["url"].lower())
        if key in seen:
            continue
        seen.add(key)
        results.append(result)
    return results


async def run_maigret(username: str) -> dict:
    report_dir = tempfile.mkdtemp(prefix="maigret_reports_")
    command = [
        "maigret",
        username,
        "--json",
        "simple",
        "--no-color",
        "--no-autoupdate",
        "--timeout",
        "10",
        "-fo",
        report_dir,
    ]
    try:
        execution = await run_command(command, timeout=MAIGRET_TIMEOUT_SECONDS)

        report_files = sorted(glob.glob(os.path.join(report_dir, "*.json")))
        if not report_files:
            raise ToolError(
                f"Maigret produced no JSON report "
                f"(exit code {execution['returncode']}): "
                f"{shorten(execution['stderr']) or 'no output files'}"
            )

        results = []
        seen = set()
        for path in report_files:
            try:
                with open(path, encoding="utf-8") as handle:
                    content = handle.read()
            except OSError:
                continue
            for payload in _extract_json_payloads(content):
                for result in parse_payload(payload):
                    key = (result["platform"].lower(), result["url"].lower())
                    if key not in seen:
                        seen.add(key)
                        results.append(result)
        return {"tool": "maigret", "results": results}
    finally:
        for leftover in glob.glob(os.path.join(report_dir, "*")):
            try:
                os.remove(leftover)
            except OSError:
                pass
        try:
            os.rmdir(report_dir)
        except OSError:
            pass
