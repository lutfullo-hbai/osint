import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from routers import (
    agent,
    audit,
    cases,
    catalog,
    company,
    config,
    correlate,
    dossier,
    watches,
    deep_scan,
    domain,
    email,
    export,
    exposure,
    footprint,
    geolocate,
    image,
    jobs,
    name,
    phone,
    sources,
    username,
)
import store
from security import limiter, user_for, weak_key_warnings


def _read_version() -> str:
    """Single source of truth: backend/VERSION (bumped on every release)."""
    try:
        return Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


APP_VERSION = _read_version()

app = FastAPI(
    title="OSINT Investigation Tool",
    description=(
        "Local OSINT helper aggregating Sherlock, Maigret, Holehe and public "
        "Truecaller page lookups."
    ),
    version=APP_VERSION,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# A wildcard would let any website open in the browser drive this local API.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS", "http://127.0.0.1:8080,http://localhost:8080"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
)

audit_logger = logging.getLogger("osint.audit")
if not audit_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(handler)
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False

MAX_AUDIT_BODY_BYTES = 64 * 1024
MAX_REQUEST_BYTES = 16 * 1024 * 1024   # the largest upload is a 15 MB image


AUDIT_QUERY_KEYS = ("query", "text", "url", "name")     # what was searched, in that order
# reads worth recording: downloads of what was found; polling GETs are not
_AUDITED_GET = re.compile(r"/(pdf|graph|audit)$|^/api/cases/[^/]+$")


def _payload(body: bytes) -> dict:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _searched(payload: dict) -> str | None:
    for key in AUDIT_QUERY_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return None


def _query_hash(body: bytes) -> str | None:
    query = _payload(body).get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    normalized = query.strip().lower().encode("utf-8")
    return "sha256:" + hashlib.sha256(normalized).hexdigest()


def _audited(method: str, path: str) -> bool:
    if not path.startswith("/api/") or method in ("OPTIONS", "HEAD"):
        return False
    return method != "GET" or bool(_AUDITED_GET.search(path))


def _store_queries() -> bool:
    return os.environ.get("AUDIT_LOG_QUERIES", "1").strip().lower() not in ("0", "false", "no")


async def _persist_audit(entry: dict) -> None:
    try:
        await asyncio.to_thread(store.add_audit, entry)
    except Exception as exc:  # noqa: BLE001 - the audit must never break a request
        audit_logger.warning(json.dumps({"event": "audit_store_failed", "error": str(exc)[:200]}))


@app.middleware("http")
async def audit_and_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    query_hash = None
    payload: dict = {}

    if request.method in ("POST", "PUT", "PATCH") and request.url.path.startswith(
        "/api/"
    ):
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
            # refuse before reading a single byte of an oversized body
            return JSONResponse(status_code=413, content={
                "status": "error",
                "message": f"Request body is larger than {MAX_REQUEST_BYTES // (1024 * 1024)} MB."})
        # only small JSON bodies are read for the audit; uploads are not
        is_json = request.headers.get("content-type", "").startswith("application/json")
        if is_json and declared.isdigit() and int(declared) <= MAX_AUDIT_BODY_BYTES:
            try:
                body = await request.body()
                query_hash = _query_hash(body)
                payload = _payload(body)
            except Exception:
                query_hash = None

    started = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        client = request.client.host if request.client else None
        status = response.status_code if response is not None else 500
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": "audit",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "client": client,
            "status": status,
            "duration_ms": duration_ms,
            "query_hash": query_hash,
        }
        audit_logger.info(json.dumps(entry, ensure_ascii=False))
        if _audited(request.method, request.url.path):
            # 8.3: who, when, what - kept locally in the cases database
            searched = _searched(payload)
            if searched and not _store_queries():
                searched = "sha256:" + hashlib.sha256(searched.lower().encode()).hexdigest()
            category = payload.get("category") if isinstance(payload.get("category"), str) else None
            await _persist_audit({
                "at": entry["ts"][:19] + "+00:00",
                "user": user_for(request.headers.get("X-API-Key"), client) or "refused",
                "client": client,
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "action": category,
                "query": searched,
                "request_id": request_id,
            })

    if response is None:
        return response
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(username.router)
app.include_router(email.router)
app.include_router(phone.router)
app.include_router(name.router)
app.include_router(company.router)
app.include_router(footprint.router)
app.include_router(exposure.router)
app.include_router(domain.router)
app.include_router(image.router)
app.include_router(catalog.router)
app.include_router(config.router)
app.include_router(cases.router)
app.include_router(deep_scan.router)
app.include_router(correlate.router)
app.include_router(dossier.router)
app.include_router(watches.router)
app.include_router(jobs.router)
app.include_router(sources.router)
app.include_router(geolocate.router)
app.include_router(agent.router)
app.include_router(export.router)
app.include_router(audit.router)


@app.get("/")
async def root():
    return {
        "name": "OSINT Investigation Tool",
        "version": APP_VERSION,
        "endpoints": [
            "/api/name",
            "/api/company",
            "/api/footprint",
            "/api/exposure",
            "/api/username",
            "/api/email",
            "/api/phone",
            "/api/domain",
            "/api/image",
            "/api/catalog",
            "/api/config",
            "/api/cases",
            "/api/jobs",
        ],
        "docs": "/docs",
    }


@app.on_event("startup")
async def _init_storage():
    store.init_db()
    for warning in weak_key_warnings():
        audit_logger.warning(json.dumps({"event": "weak_api_key", "warning": warning}))


@app.get("/health")
async def health():
    return {"status": "ok"}
