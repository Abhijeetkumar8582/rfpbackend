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
from app.middleware.endpoint_log import EndpointLogMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup; optionally run migrations."""
    from datetime import datetime, timezone, timedelta
    from app.database import SessionLocal
    from app.core.project_id import generate_project_id
    from app.models.project import Project
    from app.models.endpoint_log import EndpointLog
    from app.models.search_query import SearchQuery
    from sqlalchemy import select, text

    Base.metadata.create_all(bind=engine)
    # One-time migration: document_access_logs id from integer to UUID (drop and recreate if old schema)
    with engine.connect() as conn:
        try:
            dialect = engine.dialect.name
            if dialect == "sqlite":
                r = conn.execute(text("PRAGMA table_info(document_access_logs)")).fetchall()
                # r is list of (cid, name, type, notnull, dflt_value, pk)
                if r and any(col[1] == "id" and ("int" in (col[2] or "").lower()) for col in r):
                    conn.execute(text("DROP TABLE document_access_logs"))
                    conn.commit()
                    Base.metadata.tables["document_access_logs"].create(engine)
            elif dialect == "mysql":
                r = conn.execute(text(
                    "SELECT DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                    "AND TABLE_NAME = 'document_access_logs' AND COLUMN_NAME = 'id'"
                )).fetchone()
                if r and r[0] and "int" in str(r[0]).lower():
                    conn.execute(text("DROP TABLE document_access_logs"))
                    conn.commit()
                    Base.metadata.tables["document_access_logs"].create(engine)
        except Exception as e:
            err_msg = str(e).lower()
            if "no such table" not in err_msg and "doesn't exist" not in err_msg and "1146" not in str(e):
                try:
                    conn.rollback()
                except Exception:
                    pass
    # Add missing columns to documents if DB was created from older schema
    if "mysql" in (settings.database_url or ""):
        with engine.connect() as conn:
            for col, spec in [("cluster", "VARCHAR(128) NULL"), ("embedding_json", "TEXT NULL"), ("s3_url", "VARCHAR(2048) NULL")]:
                try:
                    conn.execute(text(f"ALTER TABLE documents ADD COLUMN {col} {spec}"))
                    conn.commit()
                except Exception as e:
                    if "1060" in str(e) or "Duplicate column" in str(e):
                        conn.rollback()
                    else:
                        raise
    else:
        with engine.connect() as conn:
            for col, spec in [("cluster", "TEXT"), ("embedding_json", "TEXT"), ("s3_url", "TEXT")]:
                try:
                    conn.execute(text(f"ALTER TABLE documents ADD COLUMN {col} {spec}"))
                    conn.commit()
                except Exception as e:
                    err_msg = str(e).lower()
                    if "duplicate column name" in err_msg or "already exists" in err_msg:
                        conn.rollback()
                    else:
                        raise
    # MySQL TEXT (~64KB) is too small for many chunk embeddings JSON — widen existing tables
    if "mysql" in (settings.database_url or ""):
        with engine.connect() as conn:
            for modify_sql in (
                "ALTER TABLE document_chunks MODIFY COLUMN embeddings_json LONGTEXT NULL",
                "ALTER TABLE documents MODIFY COLUMN embedding_json LONGTEXT NULL",
            ):
                try:
                    conn.execute(text(modify_sql))
                    conn.commit()
                except Exception as e:
                    err_s = str(e).lower()
                    if "1146" in str(e) or "doesn't exist" in err_s or "unknown column" in err_s:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                    else:
                        logging.getLogger(__name__).warning(
                            "MySQL widen column skipped or failed (%s): %s",
                            modify_sql.split("MODIFY")[0].strip(),
                            e,
                        )
                        try:
                            conn.rollback()
                        except Exception:
                            pass
    # Add missing columns to endpoint_logs (query_string, request_headers, request_body, response_headers, response_body)
    with engine.connect() as conn:
        if "mysql" in (settings.database_url or ""):
            specs = [
                ("query_string", "VARCHAR(2048) NULL"),
                ("request_headers", "LONGTEXT NULL"),
                ("request_body", "LONGTEXT NULL"),
                ("response_headers", "LONGTEXT NULL"),
                ("response_body", "LONGTEXT NULL"),
            ]
        else:
            specs = [
                ("query_string", "TEXT"), ("request_headers", "TEXT"), ("request_body", "TEXT"),
                ("response_headers", "TEXT"), ("response_body", "TEXT"),
            ]
        for col, spec in specs:
            try:
                conn.execute(text(f"ALTER TABLE endpoint_logs ADD COLUMN {col} {spec}"))
                conn.commit()
            except Exception as e:
                err_msg = str(e).lower()
                err_code = getattr(getattr(e, "orig", None), "args", [None])[0] if hasattr(e, "orig") else None
                # MySQL 1060 = duplicate column, 1146 = table doesn't exist; ignore and continue
                if (
                    "1060" in str(e)
                    or "duplicate column" in err_msg
                    or (err_code == 1060)
                    or (err_code == 1146)
                    or "doesn't exist" in err_msg
                ):
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                else:
                    raise
    # Add confidence column to rfpquestions if missing (JSON array of numbers, one per question)
    # MySQL: JSON type without default (BLOB/TEXT/JSON can't have default in strict mode)
    with engine.connect() as conn:
        if "mysql" in (settings.database_url or ""):
            rfp_sql = "ALTER TABLE rfpquestions ADD COLUMN confidence JSON"
        else:
            rfp_sql = "ALTER TABLE rfpquestions ADD COLUMN confidence TEXT NOT NULL DEFAULT '[]'"
        try:
            conn.execute(text(rfp_sql))
            conn.commit()
        except Exception as e:
            err_msg = str(e).lower()
            err_code = getattr(getattr(e, "orig", None), "args", [None])[0] if hasattr(e, "orig") else None
            if (
                "1060" in str(e)
                or "duplicate column" in err_msg
                or (err_code == 1060)
                or (err_code == 1146)
                or "doesn't exist" in err_msg
            ):
                try:
                    conn.rollback()
                except Exception:
                    pass
            else:
                raise
    # rfpquestions.conversation_id — groups SearchQuery rows for one Excel bulk Q&A thread
    with engine.connect() as conn:
        if "mysql" in (settings.database_url or ""):
            rfp_conv_sql = "ALTER TABLE rfpquestions ADD COLUMN conversation_id VARCHAR(32) NULL"
        else:
            rfp_conv_sql = "ALTER TABLE rfpquestions ADD COLUMN conversation_id VARCHAR(32) NULL"
        try:
            conn.execute(text(rfp_conv_sql))
            conn.commit()
        except Exception as e:
            err_msg = str(e).lower()
            err_code = getattr(getattr(e, "orig", None), "args", [None])[0] if hasattr(e, "orig") else None
            if (
                "1060" in str(e)
                or "duplicate column" in err_msg
                or (err_code == 1060)
                or (err_code == 1146)
                or "doesn't exist" in err_msg
            ):
                try:
                    conn.rollback()
                except Exception:
                    pass
            else:
                raise
    # rfpquestions.collaborator_user_ids — comma-separated user ids (shared My RFPs access)
    # MySQL forbids DEFAULT on TEXT; use VARCHAR (see pymysql 1101).
    with engine.connect() as conn:
        if "mysql" in (settings.database_url or ""):
            rfp_collab_sql = (
                "ALTER TABLE rfpquestions ADD COLUMN collaborator_user_ids "
                "VARCHAR(8192) NOT NULL DEFAULT ''"
            )
        else:
            rfp_collab_sql = (
                "ALTER TABLE rfpquestions ADD COLUMN collaborator_user_ids TEXT NOT NULL DEFAULT ''"
            )
        try:
            conn.execute(text(rfp_collab_sql))
            conn.commit()
        except Exception as e:
            err_msg = str(e).lower()
            err_code = getattr(getattr(e, "orig", None), "args", [None])[0] if hasattr(e, "orig") else None
            if (
                "1060" in str(e)
                or "duplicate column" in err_msg
                or (err_code == 1060)
                or (err_code == 1146)
                or "doesn't exist" in err_msg
            ):
                try:
                    conn.rollback()
                except Exception:
                    pass
            else:
                raise
    # users.vector_database — Qdrant collection name for per-user vector store
    with engine.connect() as conn:
        if "mysql" in (settings.database_url or ""):
            vdb_sql = "ALTER TABLE `users` ADD COLUMN vector_database VARCHAR(255) NULL"
        else:
            vdb_sql = "ALTER TABLE users ADD COLUMN vector_database TEXT NULL"
        try:
            conn.execute(text(vdb_sql))
            conn.commit()
        except Exception as e:
            err_msg = str(e).lower()
            err_code = getattr(getattr(e, "orig", None), "args", [None])[0] if hasattr(e, "orig") else None
            if (
                "1060" in str(e)
                or "duplicate column" in err_msg
                or (err_code == 1060)
                or (err_code == 1146)
                or "doesn't exist" in err_msg
            ):
                try:
                    conn.rollback()
                except Exception:
                    pass
            else:
                raise
    # projects — per-project chunk defaults and metadata preference (train / upload)
    with engine.connect() as conn:
        if "mysql" in (settings.database_url or ""):
            proj_cols = [
                ("chunk_size_words", "INT NULL"),
                ("chunk_overlap_words", "INT NULL"),
                ("include_metadata_in_retrieval", "TINYINT(1) NOT NULL DEFAULT 1"),
            ]
        else:
            proj_cols = [
                ("chunk_size_words", "INTEGER"),
                ("chunk_overlap_words", "INTEGER"),
                ("include_metadata_in_retrieval", "BOOLEAN NOT NULL DEFAULT 1"),
            ]
        for col, spec in proj_cols:
            try:
                conn.execute(text(f"ALTER TABLE projects ADD COLUMN {col} {spec}"))
                conn.commit()
            except Exception as e:
                err_msg = str(e).lower()
                err_code = getattr(getattr(e, "orig", None), "args", [None])[0] if hasattr(e, "orig") else None
                if (
                    "1060" in str(e)
                    or "duplicate column" in err_msg
                    or (err_code == 1060)
                    or "already exists" in err_msg
                ):
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                else:
                    raise
    # Ensure at least one default project exists
    db = SessionLocal()
    try:
        existing = db.execute(select(Project).where(Project.is_deleted == False)).scalars().first()
        if not existing:
            default = Project(
                id=generate_project_id(db),
                name="Default Project",
                description="Default project for document uploads",
                retention_days=365,
                auto_delete_enabled=False,
                is_deleted=False,
                created_at=datetime.now(timezone.utc),
            )
            db.add(default)
            db.commit()
        # Seed dummy endpoint logs if table is empty (for demo UI)
        first_log = db.execute(select(EndpointLog).limit(1)).scalars().first()
        if first_log is None:
            now = datetime.now(timezone.utc)
            dummy_logs = [
                EndpointLog(ts=now - timedelta(minutes=1), method="GET", path="/api/v1/projects", status_code=200, duration_ms=47, ip_address="192.168.1.10", user_agent="Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/121.0"),
                EndpointLog(ts=now - timedelta(minutes=2), method="POST", path="/api/v1/auth/login", status_code=200, duration_ms=120, ip_address="192.168.1.10", user_agent="Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/121.0"),
                EndpointLog(ts=now - timedelta(minutes=3), method="GET", path="/api/v1/documents?project_id=abc", status_code=200, duration_ms=89, ip_address="10.0.0.5", user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"),
                EndpointLog(ts=now - timedelta(minutes=5), method="POST", path="/api/v1/search/query", status_code=200, duration_ms=340, ip_address="192.168.1.10", user_agent="Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/121.0"),
                EndpointLog(ts=now - timedelta(minutes=7), method="GET", path="/api/v1/users", status_code=403, duration_ms=12, error_message="HTTP 403", ip_address="10.0.0.5", user_agent="curl/7.68.0"),
                EndpointLog(ts=now - timedelta(minutes=10), method="PUT", path="/api/v1/projects/1", status_code=200, duration_ms=156, ip_address="192.168.1.10", user_agent="Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/121.0"),
                EndpointLog(ts=now - timedelta(minutes=12), method="DELETE", path="/api/v1/documents/old-doc-123", status_code=204, duration_ms=78, ip_address="192.168.1.10", user_agent="Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/121.0"),
                EndpointLog(ts=now - timedelta(minutes=15), method="GET", path="/api/v1/activity/logs", status_code=200, duration_ms=52, ip_address="192.168.1.10", user_agent="Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/121.0"),
            ]
            for log in dummy_logs:
                db.add(log)
            db.commit()
        # Seed dummy search queries for conversation log (demo UI)
        first_sq = db.execute(select(SearchQuery).limit(1)).scalars().first()
        if first_sq is None:
            proj = db.execute(select(Project).where(Project.is_deleted == False)).scalars().first()
            if proj:
                from app.utils.conversation_id import generate_conversation_id
                now = datetime.now(timezone.utc)
                conv_id = generate_conversation_id()
                dummy_queries = [
                    SearchQuery(
                        datetime_=now - timedelta(minutes=2),
                        conversation_id=conv_id,
                        query_text="What is the refund policy for cancelled orders?",
                        k=5,
                        results_count=4,
                        latency_ms=320,
                        answer="Based on the policy documents, refunds for cancelled orders are processed within 5–7 business days. Orders cancelled before shipment receive a full refund; after shipment, return shipping may apply. Please refer to Section 3.2 of the Customer Terms for details.",
                        topic="refunds",
                        answer_status="answered",
                        confidence_json={"overall": 0.89, "retrieval_avg_top3": 0.91, "evidence_coverage": 0.85, "contradiction_risk": 0.02},
                    ),
                    SearchQuery(
                        datetime_=now - timedelta(minutes=8),
                        conversation_id=conv_id,
                        query_text="How do I request a leave of absence?",
                        k=5,
                        results_count=3,
                        latency_ms=280,
                        answer="To request a leave of absence, submit the Leave Request Form (HR-102) to your manager and HR at least 2 weeks in advance. For medical leave, attach the required certification. The handbook states that approval typically takes 3–5 business days.",
                        topic="HR policies",
                        answer_status="answered",
                        confidence_json={"overall": 0.82, "retrieval_avg_top3": 0.78, "evidence_coverage": 0.80, "contradiction_risk": 0.05},
                    ),
                    SearchQuery(
                        datetime_=now - timedelta(minutes=15),
                        conversation_id=conv_id,
                        query_text="What are the eligibility criteria for the wellness program?",
                        k=5,
                        results_count=5,
                        latency_ms=410,
                        answer="Full-time employees who have completed 90 days of service are eligible for the wellness program. The program includes gym reimbursement up to $50/month and annual health screenings. Part-time staff may have limited access—see the Wellness Policy addendum.",
                        topic="benefits",
                        answer_status="answered",
                        confidence_json={"overall": 0.91, "retrieval_avg_top3": 0.88, "evidence_coverage": 0.92, "contradiction_risk": 0.01},
                    ),
                    SearchQuery(
                        datetime_=now - timedelta(minutes=22),
                        conversation_id=conv_id,
                        query_text="Can we use personal devices for work email?",
                        k=5,
                        results_count=2,
                        latency_ms=195,
                        answer="The current policy does not clearly address personal device use for work email. I found references to VPN requirements and device encryption in the IT Security doc, but no explicit BYOD policy. You may want to confirm with IT or Compliance.",
                        topic="IT security",
                        answer_status="low_confidence",
                        no_answer_reason="insufficient_evidence",
                        confidence_json={"overall": 0.45, "retrieval_avg_top3": 0.52, "evidence_coverage": 0.40, "contradiction_risk": 0.10},
                    ),
                    SearchQuery(
                        datetime_=now - timedelta(minutes=35),
                        conversation_id=conv_id,
                        query_text="What is the deadline for Q4 expense reports?",
                        k=5,
                        results_count=0,
                        latency_ms=120,
                        answer=None,
                        topic=None,
                        answer_status="unanswered",
                        no_answer_reason="no_results",
                        confidence_json={"overall": 0.0, "retrieval_avg_top3": 0.0, "evidence_coverage": 0.0, "contradiction_risk": 0.0},
                    ),
                ]
                for sq in dummy_queries:
                    db.add(sq)
                db.commit()
    finally:
        db.close()

    from app.services.qdrant_process import start_qdrant_if_configured, stop_qdrant_if_started

    start_qdrant_if_configured()
    yield
    stop_qdrant_if_started()


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
app.add_middleware(EndpointLogMiddleware)

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
    env = (settings.app_env or "").lower()
    if env in ("production", "prod", "staging"):
        logging.getLogger(__name__).exception("Unhandled server error")
        detail = "An unexpected error occurred. Please try again later."
    else:
        detail = f"Processing failed: {exc!s}"
    return JSONResponse(status_code=500, content={"detail": detail}, headers=_cors_headers(request))


@app.get("/health")
def health():
    return {"status": "ok"}
