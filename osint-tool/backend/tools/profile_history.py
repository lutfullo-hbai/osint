"""When was a found profile first archived? (Wayback Machine)

The first snapshot date is a lower bound on the account's age and lets an
investigator tell a years-old account from one made last week. Only the most
trustworthy hits are checked, a few at a time, so the lookup stays quick.
"""
from __future__ import annotations

import asyncio

import httpx

AVAILABILITY_API = "https://archive.org/wayback/available"
MAX_PROFILES = 8
CONCURRENCY = 4
TIMEOUT = httpx.Timeout(8.0)
TOTAL_BUDGET_SECONDS = 20


def _first_snapshot(data: dict) -> tuple[str, str] | None:
    closest = ((data or {}).get("archived_snapshots") or {}).get("closest") or {}
    stamp = str(closest.get("timestamp") or "")
    if not closest.get("available") or len(stamp) < 8:
        return None
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}", str(closest.get("url") or "")


def _worth_checking(item: dict) -> bool:
    return item.get("confidence") == "high" or "public-api" in (item.get("sources") or [])


async def annotate_first_archived(results: list[dict]) -> None:
    """Add "first_archived" (+ snapshot URL) to the strongest profile hits."""
    targets = [r for r in results if r.get("url") and _worth_checking(r)][:MAX_PROFILES]
    if not targets:
        return
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def one(client: httpx.AsyncClient, item: dict) -> None:
        async with semaphore:
            try:
                response = await client.get(
                    AVAILABILITY_API,
                    # the snapshot closest to 1996 is the earliest one
                    params={"url": item["url"], "timestamp": "19960101"},
                )
                found = _first_snapshot(response.json()) if response.status_code == 200 else None
            except (httpx.HTTPError, ValueError):
                return
        if found:
            item["first_archived"], item["archive_url"] = found
            item["info"] = "; ".join(
                part for part in (item.get("info"), f"First archived: {found[0]}") if part
            )

    async with httpx.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": "osint-tool/1.0 (+self-hosted research tool)"}
    ) as client:
        try:
            await asyncio.wait_for(
                asyncio.gather(*(one(client, item) for item in targets)),
                timeout=TOTAL_BUDGET_SECONDS,
            )
        except asyncio.TimeoutError:
            pass  # whatever finished is kept; the rest simply has no date
