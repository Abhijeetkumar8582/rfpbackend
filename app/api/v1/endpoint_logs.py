"""Endpoint logs API — list and get by id. Admin/Super Admin only."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, desc

from app.api.deps import DbSession, CurrentUserOptional, require_admin_only
from app.models.endpoint_log import EndpointLog
from app.schemas.endpoint_log import EndpointLogResponse

router = APIRouter(prefix="/endpoint-logs", tags=["endpoint-logs"])


@router.get("", response_model=list[EndpointLogResponse])
def list_endpoint_logs(
    db: DbSession,
    current_user: CurrentUserOptional,
    method: str | None = Query(None, description="Filter by HTTP method"),
    path_contains: str | None = Query(None, alias="path", description="Filter by path substring"),
    status_code: int | None = Query(None, description="Filter by status code"),
    from_date: str | None = Query(None, description="Filter logs from this date (YYYY-MM-DD)"),
    to_date: str | None = Query(None, description="Filter logs until this date (YYYY-MM-DD)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """List endpoint logs with optional filters. Admin/Super Admin only. Ordered by newest first."""
    require_admin_only(current_user)
    q = (
        select(EndpointLog)
        .order_by(desc(EndpointLog.ts))
        .offset(skip)
        .limit(limit)
    )
    if method:
        q = q.where(EndpointLog.method == method.upper())
    if path_contains:
        q = q.where(EndpointLog.path.contains(path_contains))
    if status_code is not None:
        q = q.where(EndpointLog.status_code == status_code)
    if from_date and to_date:
        try:
            start_d = date.fromisoformat(from_date)
            end_d = date.fromisoformat(to_date)
            if start_d > end_d:
                start_d, end_d = end_d, start_d
            ts_start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=timezone.utc)
            ts_end = datetime(end_d.year, end_d.month, end_d.day, 23, 59, 59, 999999, tzinfo=timezone.utc)
            q = q.where(EndpointLog.ts >= ts_start, EndpointLog.ts <= ts_end)
        except (ValueError, TypeError):
            pass
    rows = db.execute(q).scalars().all()
    return [r for r in rows]


@router.get("/{log_id}", response_model=EndpointLogResponse)
def get_endpoint_log(log_id: int, db: DbSession, current_user: CurrentUserOptional):
    """Get a single endpoint log by id (for popup detail). Admin/Super Admin only."""
    require_admin_only(current_user)
    row = db.get(EndpointLog, log_id)
    if not row:
        raise HTTPException(status_code=404, detail="Endpoint log not found")
    return row
