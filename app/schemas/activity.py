"""Activity log schemas."""
from datetime import datetime
from pydantic import BaseModel


class ActivityLogResponse(BaseModel):
    id: int
    ts: datetime
    actor_user_id: int | None
    type: str
    project_id: int | None

    class Config:
        from_attributes = True
