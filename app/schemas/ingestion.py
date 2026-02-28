"""Ingestion job schemas."""
from datetime import datetime
from pydantic import BaseModel

from app.models.ingestion_job import IngestionJobStatus


class IngestionJobResponse(BaseModel):
    id: int
    project_id: str
    document_id: str | None
    status: IngestionJobStatus
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None

    class Config:
        from_attributes = True
