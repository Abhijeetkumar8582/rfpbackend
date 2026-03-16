"""Access Intelligence API — log and list document access (view, download, upload). List is Admin/Super Admin only."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import select, desc, func

from app.api.deps import DbSession, CurrentUserOptional, require_admin_only
from app.models.document_access_log import DocumentAccessLog
from app.schemas.document_access_log import (
    DocumentAccessLogCreate,
    DocumentAccessLogResponse,
    DocumentAccessLogListResponse,
)

router = APIRouter(prefix="/access-intelligence", tags=["access-intelligence"])


def _parse_date(date_str: str | None, end_of_day: bool = False) -> datetime | None:
    """Parse YYYY-MM-DD to UTC datetime."""
    if not date_str or not date_str.strip():
        return None
    try:
        parts = date_str.strip().split("-")
        if len(parts) != 3:
            return None
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        if end_of_day:
            return datetime(y, m, d, 23, 59, 59, 999000, tzinfo=timezone.utc)
        return datetime(y, m, d, 0, 0, 0, 0, tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return None


@router.post("/logs", response_model=DocumentAccessLogResponse)
def create_access_log(db: DbSession, body: DocumentAccessLogCreate):
    """Log a document access event (view, download, or upload). Called from File Repository when user views, downloads, or uploads a file."""
    now = datetime.now(timezone.utc)
    entry = DocumentAccessLog(
        id=str(uuid.uuid4()),
        user_id=body.user_id or None,
        username=body.username,
        date_time=now,
        document_name=body.document_name,
        document_id=body.document_id,
        access_level=body.access_level,
        action=body.action,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/logs", response_model=DocumentAccessLogListResponse)
def list_access_logs(
    db: DbSession,
    current_user: CurrentUserOptional,
    user_id: str | None = None,
    username: str | None = None,
    document_name: str | None = None,
    document_id: str | None = None,
    access_level: str | None = None,
    action: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """List document access logs with optional filters. Admin/Super Admin only. Used by Access Intelligence page."""
    require_admin_only(current_user)
    q = select(DocumentAccessLog)
    if user_id:
        q = q.where(DocumentAccessLog.user_id == user_id)
    if username:
        q = q.where(DocumentAccessLog.username.ilike(f"%{username}%"))
    if document_name:
        q = q.where(DocumentAccessLog.document_name.ilike(f"%{document_name}%"))
    if document_id:
        q = q.where(DocumentAccessLog.document_id == document_id)
    if access_level:
        q = q.where(DocumentAccessLog.access_level == access_level)
    if action:
        q = q.where(DocumentAccessLog.action == action)
    from_dt = _parse_date(from_date, end_of_day=False)
    if from_dt is not None:
        q = q.where(DocumentAccessLog.date_time >= from_dt)
    to_dt = _parse_date(to_date, end_of_day=True)
    if to_dt is not None:
        q = q.where(DocumentAccessLog.date_time <= to_dt)

    # Total count with same filters
    count_q = select(func.count()).select_from(DocumentAccessLog)
    if user_id:
        count_q = count_q.where(DocumentAccessLog.user_id == user_id)
    if username:
        count_q = count_q.where(DocumentAccessLog.username.ilike(f"%{username}%"))
    if document_name:
        count_q = count_q.where(DocumentAccessLog.document_name.ilike(f"%{document_name}%"))
    if document_id:
        count_q = count_q.where(DocumentAccessLog.document_id == document_id)
    if access_level:
        count_q = count_q.where(DocumentAccessLog.access_level == access_level)
    if action:
        count_q = count_q.where(DocumentAccessLog.action == action)
    if from_dt is not None:
        count_q = count_q.where(DocumentAccessLog.date_time >= from_dt)
    if to_dt is not None:
        count_q = count_q.where(DocumentAccessLog.date_time <= to_dt)
    total = db.execute(count_q).scalar() or 0

    q = q.order_by(desc(DocumentAccessLog.date_time)).offset(skip).limit(limit)
    rows = db.execute(q).scalars().all()
    return DocumentAccessLogListResponse(items=list(rows), total=total)
