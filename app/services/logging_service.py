"""Service for writing endpoint and conversation logs."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.endpoint_log import EndpointLog
from app.models.conversation_log import ConversationLog


def log_endpoint(
    db: Session,
    *,
    method: str,
    path: str,
    status_code: int,
    activity_id: int | None = None,
    duration_ms: int | None = None,
    request_id: str | None = None,
    actor_user_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    error_message: str | None = None,
    query_string: str | None = None,
    request_headers: str | None = None,
    request_body: str | None = None,
    response_headers: str | None = None,
    response_body: str | None = None,
) -> EndpointLog:
    """Create an endpoint_logs row. Returns the created EndpointLog instance."""
    entry = EndpointLog(
        activity_id=activity_id,
        ts=datetime.now(timezone.utc),
        method=method.upper(),
        path=path,
        status_code=status_code,
        duration_ms=duration_ms,
        request_id=request_id,
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        error_message=error_message,
        query_string=query_string,
        request_headers=request_headers,
        request_body=request_body,
        response_headers=response_headers,
        response_body=response_body,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def log_conversation_message(
    db: Session,
    *,
    conversation_id: str,
    message_index: int,
    role: str,
    content: str,
    activity_id: int | None = None,
    actor_user_id: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> ConversationLog:
    """Create a conversation_logs row. Returns the created ConversationLog instance."""
    entry = ConversationLog(
        activity_id=activity_id,
        ts=datetime.now(timezone.utc),
        conversation_id=conversation_id,
        message_index=message_index,
        role=role,
        content=content,
        actor_user_id=actor_user_id,
        metadata_json=metadata_json,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
