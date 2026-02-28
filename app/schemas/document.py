"""Document schemas."""
from datetime import datetime
from pydantic import BaseModel

from app.models.document import DocumentStatus


class DocumentCreate(BaseModel):
    project_id: str
    filename: str
    content_type: str
    size_bytes: int


class DocumentUpdate(BaseModel):
    """Optional fields for updating document metadata (e.g. after GPT or manual edit)."""
    doc_title: str | None = None
    doc_description: str | None = None
    doc_type: str | None = None
    tags: list[str] | None = None  # serialized to tags_json
    taxonomy_suggestions: dict[str, list[str]] | None = None  # serialized to taxonomy_suggestions_json


class DocumentResponse(BaseModel):
    id: str
    project_id: str
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    uploaded_by: str
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
    document_id: str
    title: str
    description: str
    doc_type: str
    tags: list[str]
    taxonomy_suggestions: dict[str, list[str]]
