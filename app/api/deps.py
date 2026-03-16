"""FastAPI dependencies — DB session, auth placeholder."""
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import decode_token
from app.models.user import User, UserRole

# Type alias for dependency injection
DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Return current user if valid Bearer token present; else raise 401. Use for endpoints that must record who performed the action."""
    user = get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


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
    user = db.get(User, sub)
    if not user or not getattr(user, "is_active", True):
        return None
    return user


# Required current user (for endpoints that must record actor_user_id, e.g. search)
CurrentUser = Annotated[User, Depends(get_current_user)]

# Optional current user (for endpoints that allow anonymous access)
CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]


def require_admin_or_manager(current_user: User | None) -> None:
    """Raise 401 if not authenticated, 403 if not Super Admin or Admin. Use for upload/train etc."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if current_user.role not in (UserRole.admin, UserRole.manager):
        raise HTTPException(
            status_code=403,
            detail="Only Super Admin or Admin can add files or train data.",
        )


def require_admin_only(current_user: User | None) -> None:
    """Raise 401 if not authenticated, 403 if not Super Admin or Admin. Use for Activity Log, Access Intelligence, Endpoint Log, Conversation Log, Integrations."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if current_user.role not in (UserRole.admin, UserRole.manager):
        raise HTTPException(
            status_code=403,
            detail="Only Super Admin or Admin can access this.",
        )
