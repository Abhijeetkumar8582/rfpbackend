"""Document access log schemas — Access Intelligence."""
from datetime import datetime
from pydantic import BaseModel, Field


class DocumentAccessLogCreate(BaseModel):
    """Payload to log a document access event (view, download, upload)."""
    user_id: str | None = Field(None, description="User ID; optional if not authenticated")
    username: str = Field(..., description="User display name")
    document_name: str = Field(..., description="Name of the document")
    document_id: str | None = Field(None, description="Document ID if available")
    access_level: str = Field(..., description="open_for_all, team_specific, high_security")
    action: str = Field(..., description="view, download, or upload")


class DocumentAccessLogResponse(BaseModel):
    """Single document access log row as returned by API."""
    id: str
    user_id: str | None
    username: str
    date_time: datetime
    document_name: str
    document_id: str | None
    access_level: str
    action: str

    model_config = {"from_attributes": True}


class DocumentAccessLogListResponse(BaseModel):
    """Paginated list of document access logs."""
    items: list[DocumentAccessLogResponse]
    total: int
