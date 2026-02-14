"""Audit logs API — list security/governance events (stub)."""
from fastapi import APIRouter
from app.api.deps import DbSession

from app.schemas.audit import AuditLogResponse

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs", response_model=list[AuditLogResponse])
def list_audit_logs(
    db: DbSession,
    project_id: int | None = None,
    actor_user_id: int | None = None,
    action: str | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """List audit logs. TODO: add auth (admin only), filters, date range."""
    raise NotImplementedError("TODO: implement list audit logs")
