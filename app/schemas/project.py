"""Project schemas."""
from datetime import datetime
from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    retention_days: int = 365
    auto_delete_enabled: bool = False


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    retention_days: int | None = None
    auto_delete_enabled: bool | None = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str | None
    retention_days: int
    auto_delete_enabled: bool
    is_deleted: bool
    created_at: datetime

    class Config:
        from_attributes = True
