"""Activity logs API — list and create activity stream (actor = user name, common for all applicants)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from app.api.deps import DbSession
from app.models.activity_log import ActivityLog
from app.schemas.activity import ActivityLogCreate, ActivityLogResponse
from app.services.activity_log import log_activity

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("/logs", response_model=list[ActivityLogResponse])
def list_activity_logs(
    db: DbSession,
    actor: str | None = None,
    event_action: str | None = None,
    severity: str | None = None,
    system: str | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """List activity logs. Filter by actor, event_action, severity, system."""
    q = select(ActivityLog).order_by(desc(ActivityLog.timestamp)).offset(skip).limit(limit)
    if actor:
        q = q.where(ActivityLog.actor == actor)
    if event_action:
        q = q.where(ActivityLog.event_action == event_action)
    if severity:
        q = q.where(ActivityLog.severity == severity)
    if system:
        q = q.where(ActivityLog.system == system)
    rows = db.execute(q).scalars().all()
    return [r for r in rows]


@router.post("/logs", response_model=ActivityLogResponse)
def create_activity_log(db: DbSession, body: ActivityLogCreate):
    """Create one activity log entry (e.g. from middleware or after login)."""
    entry = log_activity(
        db,
        actor=body.actor,
        event_action=body.event_action,
        target_resource=body.target_resource,
        severity=body.severity,
        ip_address=body.ip_address,
        system=body.system or "web",
    )
    return entry
