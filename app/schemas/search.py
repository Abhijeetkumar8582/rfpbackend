"""Search schemas."""
from datetime import datetime
from pydantic import BaseModel


class SearchRequest(BaseModel):
    query_text: str
    k: int = 5
    filters_json: dict | None = None


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
    actor_user_id: int
    project_id: int
    query_text: str
    k: int
    results_count: int
    latency_ms: int | None

    class Config:
        from_attributes = True
