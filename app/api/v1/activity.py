"""Activity logs API — list and create activity stream (actor = user name, common for all applicants)."""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter
from sqlalchemy import select, desc, func, or_
from app.api.deps import DbSession, CurrentUserOptional, require_admin_only
from app.models.activity_log import ActivityLog
from app.schemas.activity import ActivityLogCreate, ActivityLogResponse, ActivityLogListResponse
from app.services.activity_log import log_activity

router = APIRouter(prefix="/activity", tags=["activity"])


def _parse_date(date_str: str | None, end_of_day: bool = False) -> datetime | None:
    """Parse YYYY-MM-DD to UTC datetime. If end_of_day, use 23:59:59.999."""
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


def _base_query(actor=None, event_action=None, severity=None, severity_in=None, system=None, days=None, from_date=None, to_date=None, q_search=None):
    """Build base select and count query with optional filters."""
    base_where = []
    if actor:
        base_where.append(ActivityLog.actor == actor)
    if event_action:
        base_where.append(ActivityLog.event_action == event_action)
    if severity:
        base_where.append(ActivityLog.severity == severity)
    if severity_in:
        parts = [s.strip() for s in severity_in.split(",") if s.strip()]
        if parts:
            base_where.append(or_(*[ActivityLog.severity.ilike(p) for p in parts]))
    if system:
        base_where.append(ActivityLog.system == system)
    if days is not None and days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=int(days))
        base_where.append(ActivityLog.timestamp >= since)
    from_dt = _parse_date(from_date, end_of_day=False)
    if from_dt is not None:
        base_where.append(ActivityLog.timestamp >= from_dt)
    to_dt = _parse_date(to_date, end_of_day=True)
    if to_dt is not None:
        base_where.append(ActivityLog.timestamp <= to_dt)
    if q_search:
        search = f"%{q_search.strip()}%"
        base_where.append(
            or_(
                ActivityLog.actor.ilike(search),
                ActivityLog.event_action.ilike(search),
                ActivityLog.target_resource.ilike(search),
                ActivityLog.ip_address.ilike(search),
            )
        )
    return base_where


@router.get("/logs", response_model=ActivityLogListResponse)
def list_activity_logs(
    db: DbSession,
    current_user: CurrentUserOptional,
    actor: str | None = None,
    event_action: str | None = None,
    severity: str | None = None,
    severity_in: str | None = None,
    system: str | None = None,
    q: str | None = None,
    days: int | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """List activity logs with pagination. Admin/Super Admin only. Filter by actor, event_action, severity, severity_in, system, q (search), days, from_date, to_date. Returns total count and last-7-days total."""
    require_admin_only(current_user)
    base_where = _base_query(
        actor=actor,
        event_action=event_action,
        severity=severity,
        severity_in=severity_in,
        system=system,
        days=days,
        from_date=from_date,
        to_date=to_date,
        q_search=q,
    )

    # Total count for current filters (for pagination)
    q_count = select(func.count()).select_from(ActivityLog)
    for w in base_where:
        q_count = q_count.where(w)
    total = db.execute(q_count).scalar() or 0

    # Total count for last 7 days (always, for stats)
    since_7 = datetime.now(timezone.utc) - timedelta(days=7)
    q_7 = select(func.count()).select_from(ActivityLog).where(ActivityLog.timestamp >= since_7)
    total_last_7_days = db.execute(q_7).scalar() or 0

    # Paginated items
    q = select(ActivityLog).order_by(desc(ActivityLog.timestamp)).offset(skip).limit(limit)
    for w in base_where:
        q = q.where(w)
    rows = db.execute(q).scalars().all()
    items = [r for r in rows]

    return ActivityLogListResponse(items=items, total=total, total_last_7_days=total_last_7_days)


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
