"""Activity log service — helper to record activity (common for all applicants by actor name)."""
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog


def log_activity(
    db: Session,
    actor: str,
    event_action: str,
    target_resource: str = "",
    severity: str = "info",
    ip_address: str | None = None,
    system: str = "",
) -> ActivityLog:
    """
    Record one activity log entry. Use the user's display name as actor so the same
    person is one actor across different accounts.
    """
    entry = ActivityLog(
        timestamp=datetime.now(timezone.utc),
        actor=actor,
        event_action=event_action,
        target_resource=target_resource,
        severity=severity,
        ip_address=ip_address,
        system=system or "web",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
