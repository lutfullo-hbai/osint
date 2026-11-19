"""The version shown by the API comes from backend/VERSION."""
import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import main


def test_version_file_is_semver():
    text = Path(main.__file__).with_name("VERSION").read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", text)
    assert main.APP_VERSION == text == main.app.version


@pytest.mark.asyncio
async def test_root_reports_version():
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        body = (await client.get("/")).json()
    assert body["version"] == main.APP_VERSION
