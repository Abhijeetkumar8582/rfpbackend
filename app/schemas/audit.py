"""Audit log schemas."""
from datetime import datetime
from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: int
    ts: datetime
    actor_user_id: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    project_id: str | None
    ip: str | None
    success: bool
    failure_reason: str | None

    class Config:
        from_attributes = True
