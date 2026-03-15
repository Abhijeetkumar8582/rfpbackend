"""Conversation ID for search_queries — conv_<ULID>, valid 24h from first message in conversation."""
from datetime import datetime, timezone, timedelta

from ulid import ULID


CONVERSATION_TTL_HOURS = 24
CONVERSATION_ID_PREFIX = "conv_"


def generate_conversation_id() -> str:
    """
    Generate a new conversation_id in production format: conv_<ULID>.
    Example: conv_01HVX8MZ7K8A9Q2R5T6YB3N4PD
    - Globally unique, sortable by creation time, safe in distributed systems.
    - Total length 31 chars (conv_=5 + ULID=26), fits VARCHAR(32).
    """
    return f"{CONVERSATION_ID_PREFIX}{str(ULID()).upper()}"


def is_conversation_valid(conversation_created_ts: datetime | None, now: datetime | None = None) -> bool:
    """
    Return True if the conversation is still within the 24h validity window.
    conversation_created_ts: timestamp of the first query in the conversation (timezone-aware).
    """
    if conversation_created_ts is None:
        return False
    now = now or datetime.now(timezone.utc)
    if conversation_created_ts.tzinfo is None:
        conversation_created_ts = conversation_created_ts.replace(tzinfo=timezone.utc)
    return (now - conversation_created_ts) < timedelta(hours=CONVERSATION_TTL_HOURS)
