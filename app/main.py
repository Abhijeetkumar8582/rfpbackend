"""RFP Backend — FastAPI application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app.api.v1.router import api_router
from app import models  # noqa: F401 — register models with Base.metadata


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup; optionally run migrations."""
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown: close connections, etc.


app = FastAPI(
    title="RFP Backend API",
    description="Backend for RFP document management, search, and audit",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health")
def health():
    return {"status": "ok"}
