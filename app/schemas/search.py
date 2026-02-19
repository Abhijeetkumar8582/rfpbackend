"""Search schemas."""
import uuid
from datetime import datetime
from pydantic import BaseModel


class SearchRequest(BaseModel):
    query_text: str
    project_id: int
    k: int = 5
    filters_json: dict | None = None


class SearchResultItem(BaseModel):
    """One chunk hit from ChromaDB (question embedding vs document chunk embeddings)."""
    content: str
    document_id: int
    filename: str
    chunk_index: int
    distance: float
    score: float  # 1 - distance for cosine-like; higher = more similar


class SearchResponse(BaseModel):
    query_text: str
    project_id: int
    k: int
    results: list[SearchResultItem]


class SearchAnswerResponse(BaseModel):
    """Search + GPT answer (RAG): same as SearchResponse plus answer text."""
    query_text: str
    project_id: int
    k: int
    results: list[SearchResultItem]
    answer: str


class SearchQueryCreate(BaseModel):
    project_id: int
    query_text: str
    k: int = 5
    filters_json: dict | None = None
    results_count: int = 0
    latency_ms: int | None = None


class SearchQueryResponse(BaseModel):
    id: int
    ts: datetime
    actor_user_id: uuid.UUID | None
    project_id: int
    query_text: str
    k: int
    results_count: int
    latency_ms: int | None
    answer: str | None = None

    class Config:
        from_attributes = True
