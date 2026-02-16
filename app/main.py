"""RFP Backend — FastAPI application entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)

from app.config import settings
from app.database import engine, Base
from app.api.v1.router import api_router
from app import models  # noqa: F401 — register models with Base.metadata


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup; optionally run migrations."""
    from app.database import SessionLocal
    from app.models.project import Project
    from sqlalchemy import select, text

    Base.metadata.create_all(bind=engine)
    # Add missing columns to documents if DB was created from older schema (e.g. Unknown column 'cluster')
    if "mysql" in (settings.database_url or ""):
        with engine.connect() as conn:
            for col, spec in [("cluster", "VARCHAR(128) NULL"), ("embedding_json", "TEXT NULL")]:
                try:
                    conn.execute(text(f"ALTER TABLE documents ADD COLUMN {col} {spec}"))
                    conn.commit()
                except Exception as e:
                    if "1060" in str(e) or "Duplicate column" in str(e):
                        conn.rollback()
                    else:
                        raise
    # Ensure at least one default project exists
    db = SessionLocal()
    try:
        existing = db.execute(select(Project).where(Project.is_deleted == False)).scalars().first()
        if not existing:
            from datetime import datetime, timezone
            default = Project(
                name="Default Project",
                description="Default project for document uploads",
                retention_days=365,
                auto_delete_enabled=False,
                is_deleted=False,
                created_at=datetime.now(timezone.utc),
            )
            db.add(default)
            db.commit()
    finally:
        db.close()
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


def _cors_headers(request: Request):
    origin = request.headers.get("origin") or ""
    allow_origin = origin if origin in settings.cors_origins_list else (settings.cors_origins_list[0] if settings.cors_origins_list else "*")
    return {
        "Access-Control-Allow-Origin": allow_origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }


@app.exception_handler(Exception)
async def add_cors_to_exception_response(request: Request, exc: Exception):
    """Ensure CORS headers on all exception responses so browser can read error (avoids 'blocked by CORS policy')."""
    from fastapi.exceptions import HTTPException as FastAPIHTTPException
    if isinstance(exc, FastAPIHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=_cors_headers(request))
    return JSONResponse(status_code=500, content={"detail": f"Processing failed: {exc!s}"}, headers=_cors_headers(request))


@app.get("/health")
def health():
    return {"status": "ok"}
