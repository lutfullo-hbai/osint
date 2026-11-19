"""Shared test setup."""
import pytest


@pytest.fixture(autouse=True)
def _offline_orginfo(monkeypatch):
    """Name and company searches also ask orginfo.uz (7.4). Tests never reach
    the real site: an empty page means "no matches". Tests of orginfo itself
    patch _get_page again with their own pages."""
    from tools import orginfo

    async def empty_page(path):
        return ""

    monkeypatch.setattr(orginfo, "_get_page", empty_page)
