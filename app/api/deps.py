"""FastAPI dependencies — DB session, auth placeholder."""
import uuid
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import decode_token
from app.models.user import User

# Type alias for dependency injection
DbSession = Annotated[Session, Depends(get_db)]


def get_current_user_optional(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User | None:
    """Return current user if valid Bearer token present; else None. Does not raise."""
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        user_id = uuid.UUID(sub)
    except (TypeError, ValueError):
        return None
    user = db.get(User, user_id)
    if not user or not getattr(user, "is_active", True):
        return None
    return user


# Optional current user (for logging search queries when auth is present)
CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]
