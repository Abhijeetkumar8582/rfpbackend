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
    id: str
    name: str
    description: str | None
    retention_days: int
    auto_delete_enabled: bool
    is_deleted: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TrainDatasourceConfig(BaseModel):
    """Optional config for training (chunk/embedding settings). Stored for future re-chunking; sync uses existing DB chunks."""

    chunk_size_words: int | None = None
    chunk_overlap_words: int | None = None
    embedding_model: str | None = None
    include_metadata: bool | None = None


class TrainDatasourceResponse(BaseModel):
    message: str
    documents_synced: int
    chunks_synced: int
