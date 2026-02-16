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
    doc_title: str | None = None
    doc_description: str | None = None
    doc_type: str | None = None
    tags_json: str | None = None
    taxonomy_suggestions_json: str | None = None

    class Config:
        from_attributes = True


class DocumentChunkItem(BaseModel):
    index: int
    content: str
    tokens: int


class DocumentChunksResponse(BaseModel):
    chunks: list[DocumentChunkItem]
    chunk_count: int


class DocumentMetadataResponse(BaseModel):
    document_id: int
    title: str
    description: str
    doc_type: str
    tags: list[str]
    taxonomy_suggestions: dict[str, list[str]]
