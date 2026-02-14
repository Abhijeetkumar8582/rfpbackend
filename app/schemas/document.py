"""Document schemas."""
from datetime import datetime
from pydantic import BaseModel

from app.models.document import DocumentStatus


class DocumentCreate(BaseModel):
    project_id: int
    filename: str
    content_type: str
    size_bytes: int


class DocumentResponse(BaseModel):
    id: int
    project_id: int
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    uploaded_by: int
    uploaded_at: datetime
    ingested_at: datetime | None
    deleted_at: datetime | None
    cluster: str | None = None
    storage_path: str = ""

    class Config:
        from_attributes = True
