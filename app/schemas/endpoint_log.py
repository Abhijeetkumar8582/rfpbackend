"""Endpoint log schemas for API responses."""
from datetime import datetime
from pydantic import BaseModel, Field


class EndpointLogResponse(BaseModel):
    """Endpoint log row as returned in list/detail."""
    id: int
    ts: datetime
    method: str
    path: str
    status_code: int
    duration_ms: int | None
    request_id: str | None
    actor_user_id: str | None
    ip_address: str | None
    user_agent: str | None
    error_message: str | None
    activity_id: int | None
    query_string: str | None = None
    request_headers: str | None = None
    request_body: str | None = None
    response_headers: str | None = None
    response_body: str | None = None

    model_config = {"from_attributes": True}
