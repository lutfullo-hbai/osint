import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from routers import (
    catalog,
    company,
    domain,
    email,
    footprint,
    image,
    jobs,
    name,
    phone,
    username,
)
from security import limiter

app = FastAPI(
    title="OSINT Investigation Tool",
    description=(
        "Local OSINT helper aggregating Sherlock, Maigret, Holehe and public "
        "Truecaller page lookups."
    ),
    version="1.0.0",
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
    allow_methods=["GET", "POST"],
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


def _query_hash(body: bytes) -> str | None:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    normalized = query.strip().lower().encode("utf-8")
    return "sha256:" + hashlib.sha256(normalized).hexdigest()


@app.middleware("http")
async def audit_and_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    query_hash = None

    if request.method in ("POST", "PUT", "PATCH") and request.url.path.startswith(
        "/api/"
    ):
        try:
            body = await request.body()
            if len(body) <= MAX_AUDIT_BODY_BYTES:
                query_hash = _query_hash(body)
        except Exception:
            query_hash = None

    started = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": "audit",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "client": request.client.host if request.client else None,
            "status": response.status_code if response is not None else 500,
            "duration_ms": duration_ms,
            "query_hash": query_hash,
        }
        audit_logger.info(json.dumps(entry, ensure_ascii=False))

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
app.include_router(domain.router)
app.include_router(image.router)
app.include_router(catalog.router)
app.include_router(jobs.router)


@app.get("/")
async def root():
    return {
        "name": "OSINT Investigation Tool",
        "version": "1.0.0",
        "endpoints": [
            "/api/name",
            "/api/company",
            "/api/footprint",
            "/api/username",
            "/api/email",
            "/api/phone",
            "/api/domain",
            "/api/image",
            "/api/catalog",
            "/api/jobs",
        ],
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
