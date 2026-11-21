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


@pytest.fixture(autouse=True)
def _test_hosts(monkeypatch):
    """The API refuses unknown Host names (8b.1); test clients use these."""
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost,127.0.0.1,::1,test,testserver")


@pytest.fixture(autouse=True)
def _fresh_memory_cache():
    """Cached answers (GitHub profiles are kept a day, 10.2) must not leak between tests."""
    from cache import clear_memory_cache
    clear_memory_cache()
    yield
    clear_memory_cache()
