import os

from fastapi import Header, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address

DEFAULT_HEAVY_LIMIT = "4/minute"
DEFAULT_LIGHT_LIMIT = "15/minute"
DEFAULT_GENERAL_LIMIT = "60/minute"
DEFAULT_POLL_LIMIT = "120/minute"


def _limit(env_name: str, default: str):
    def limit_value(*_args, **_kwargs) -> str:
        return os.environ.get(env_name, default)

    return limit_value


heavy_limit = _limit("RATE_LIMIT_HEAVY", DEFAULT_HEAVY_LIMIT)
light_limit = _limit("RATE_LIMIT_LIGHT", DEFAULT_LIGHT_LIMIT)
general_limit = _limit("RATE_LIMIT_GENERAL", DEFAULT_GENERAL_LIMIT)
poll_limit = _limit("RATE_LIMIT_POLL", DEFAULT_POLL_LIMIT)

limiter = Limiter(key_func=get_remote_address, headers_enabled=True)


def api_key_expected() -> str:
    return os.environ.get("OSINT_API_KEY", "").strip()


async def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    expected = api_key_expected()
    if expected and x_api_key != expected:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
