from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import catalog, domain, email, name, phone, username

app = FastAPI(
    title="OSINT Investigation Tool",
    description=(
        "Local OSINT helper aggregating Sherlock, Maigret, Holehe and public "
        "Truecaller page lookups."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(username.router)
app.include_router(email.router)
app.include_router(phone.router)
app.include_router(name.router)
app.include_router(domain.router)
app.include_router(catalog.router)


@app.get("/")
async def root():
    return {
        "name": "OSINT Investigation Tool",
        "version": "1.0.0",
        "endpoints": [
            "/api/name",
            "/api/username",
            "/api/email",
            "/api/phone",
            "/api/domain",
            "/api/catalog",
        ],
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
