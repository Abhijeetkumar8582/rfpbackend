"""Endpoint logs API — list and get by id."""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, desc

from app.api.deps import DbSession
from app.models.endpoint_log import EndpointLog
from app.schemas.endpoint_log import EndpointLogResponse

router = APIRouter(prefix="/endpoint-logs", tags=["endpoint-logs"])


@router.get("", response_model=list[EndpointLogResponse])
def list_endpoint_logs(
    db: DbSession,
    method: str | None = Query(None, description="Filter by HTTP method"),
    path_contains: str | None = Query(None, alias="path", description="Filter by path substring"),
    status_code: int | None = Query(None, description="Filter by status code"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """List endpoint logs with optional filters. Ordered by newest first."""
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
    rows = db.execute(q).scalars().all()
    return [r for r in rows]


@router.get("/{log_id}", response_model=EndpointLogResponse)
def get_endpoint_log(log_id: int, db: DbSession):
    """Get a single endpoint log by id (for popup detail)."""
    row = db.get(EndpointLog, log_id)
    if not row:
        raise HTTPException(status_code=404, detail="Endpoint log not found")
    return row
