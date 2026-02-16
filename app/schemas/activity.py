"""Activity log schemas."""
from datetime import datetime
from pydantic import BaseModel, Field


class ActivityLogCreate(BaseModel):
    """Payload to create an activity log entry."""
    actor: str = Field(..., description="User display name (common for all applicants)")
    event_action: str = Field(..., description="e.g. login, upload, view")
    target_resource: str = Field(default="", description="e.g. RFP, Document")
    severity: str = Field(default="info", description="info, warning, error, critical")
    ip_address: str | None = None
    system: str = Field(default="", description="e.g. web, api, admin")


class ActivityLogResponse(BaseModel):
    """Activity log row as returned by API."""
    id: int
    timestamp: datetime
    actor: str
    event_action: str
    target_resource: str
    severity: str
    ip_address: str | None
    system: str

    model_config = {"from_attributes": True}
