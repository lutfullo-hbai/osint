"""Rate limits and access (ROADMAP 8.4).

Access rules:
  - OSINT_API_KEY=<key>                  one key, its holder is "admin"
  - OSINT_USERS=alice:<key>,bob:<key>    named keys, so the audit log (8.3)
                                         records who searched; admin can be
                                         listed here too ("admin:<key>")
  - no key at all                        allowed only from this machine or a
                                         private network; a request from a
                                         public address gets 403 unless
                                         ALLOW_OPEN_ACCESS=1 (the tool is then
                                         exposed on purpose, at your risk)
"""
import hmac
import ipaddress
import os
import re

from fastapi import Depends, Header, HTTPException, Request
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


ADMIN = "admin"
LOCAL = "local"                      # no keys configured, request from this machine / LAN
REFUSED = "refused"                  # how the audit log names a rejected request
# names with a meaning of their own: "admin" in OSINT_USERS would grant admin rights
RESERVED_NAMES = {ADMIN, LOCAL, REFUSED}
MIN_KEY_LENGTH = 16
_USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
DEFAULT_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def api_key_expected() -> str:
    return os.environ.get("OSINT_API_KEY", "").strip()


def configured_users() -> dict[str, str]:
    """{key: user name}. Malformed entries are skipped (see weak_key_warnings)."""
    users: dict[str, str] = {}
    for entry in os.environ.get("OSINT_USERS", "").split(","):
        name, sep, key = entry.strip().partition(":")
        name = name.strip()
        if sep and _USER_RE.match(name) and name.lower() not in RESERVED_NAMES and key.strip():
            users[key.strip()] = name
    single = api_key_expected()
    if single:
        users.setdefault(single, ADMIN)
    return users


def weak_key_warnings() -> list[str]:
    """Shown at startup: short keys and OSINT_USERS entries that were ignored."""
    warnings = [f"API key of '{name}' is shorter than {MIN_KEY_LENGTH} characters"
                for key, name in configured_users().items() if len(key) < MIN_KEY_LENGTH]
    for entry in os.environ.get("OSINT_USERS", "").split(","):
        name = entry.strip().partition(":")[0].strip()
        if name.lower() in RESERVED_NAMES:
            warnings.append(f"OSINT_USERS entry '{name}' ignored: the name is reserved "
                            "(the admin key is OSINT_API_KEY)")
    return warnings


def allowed_hosts() -> tuple[str, ...] | None:
    """Host names the API answers to (DNS-rebinding guard, ROADMAP 8b.1).

    ALLOWED_HOSTS set: always enforced ("*" turns the check off).
    Not set: enforced only without keys, the mode a rebinding page could
    abuse, with localhost names; with keys an attacker page has no key.
    """
    raw = os.environ.get("ALLOWED_HOSTS", "").strip()
    if raw:
        hosts = tuple(h.strip().lower() for h in raw.split(",") if h.strip())
        return None if "*" in hosts else hosts
    if configured_users():
        return None
    return DEFAULT_LOCAL_HOSTS


def host_allowed(host_header: str | None) -> bool:
    hosts = allowed_hosts()
    if hosts is None:
        return True
    host = (host_header or "").strip().lower()
    if host.startswith("["):                      # [::1]:8000
        host = host[1:].split("]")[0]
    elif host.count(":") == 1:
        host = host.split(":")[0]
    return host in hosts


def _is_private_client(host: str | None) -> bool:
    if not host:
        return False
    if host in ("testclient", "testserver", "localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_private or ip.is_link_local


def open_access_allowed() -> bool:
    return os.environ.get("ALLOW_OPEN_ACCESS", "").strip().lower() in ("1", "true", "yes")


def user_for(key: str | None, client_host: str | None) -> str | None:
    """The user a request acts as, or None when it must be refused."""
    users = configured_users()
    if users:
        if not key:
            return None
        for expected, name in users.items():
            if hmac.compare_digest(key.encode(), expected.encode()):
                return name
        return None
    if _is_private_client(client_host) or open_access_allowed():
        return LOCAL
    return None


async def verify_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    host = request.client.host if request.client else None
    user = user_for(x_api_key, host)
    if user is None:
        if not configured_users():
            raise HTTPException(
                status_code=403,
                detail=("This API is reachable from the network without a key. Set OSINT_API_KEY "
                        "(or OSINT_USERS) on the server, or ALLOW_OPEN_ACCESS=1 to expose it on purpose."),
            )
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
    request.state.user = user
    return user


async def require_admin(user: str = Depends(verify_api_key)) -> str:
    """Audit log and full deletion: the admin key, or anyone when no keys are set."""
    if user not in (ADMIN, LOCAL):
        raise HTTPException(status_code=403, detail="Only the admin key can do this.")
    return user
