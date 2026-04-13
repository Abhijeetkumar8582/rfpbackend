"""Project schemas."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    retention_days: int
    auto_delete_enabled: bool
    is_deleted: bool
    created_at: datetime
    # Per-project ingestion defaults (null chunk fields = use server env defaults on upload)
    chunk_size_words: int | None = None
    chunk_overlap_words: int | None = None
    include_metadata_in_retrieval: bool = True


class TrainDatasourceConfig(BaseModel):
    """
    Optional fields update this project's saved defaults for **new uploads**.
    Sync always rebuilds Qdrant from existing DB chunks (no re-embedding).
    """

    model_config = ConfigDict(extra="ignore")

    chunk_size_words: int | None = Field(None, ge=50, le=500)
    chunk_overlap_words: int | None = Field(None, ge=0, le=120)
    include_metadata: bool | None = Field(
        None,
        description="Persist preference for context enrichment; reserved for future RAG behavior.",
    )


class TrainDatasourceResponse(BaseModel):
    message: str
    documents_synced: int
    chunks_synced: int
    chunk_size_words: int | None = None
    chunk_overlap_words: int | None = None
    include_metadata_in_retrieval: bool = True
