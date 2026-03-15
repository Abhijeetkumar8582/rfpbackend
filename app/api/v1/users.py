"""Users API — list, get, update, delete."""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession, CurrentUserOptional
from app.models.user import User
from app.schemas.user import UserResponse, UserUpdate
from app.schemas.common import Message

router = APIRouter(prefix="/users", tags=["users"])


def _require_auth(current_user: CurrentUserOptional):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")


def _get_user_or_404(db: DbSession, user_id: str) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("", response_model=list[UserResponse])
def list_users(db: DbSession, current_user: CurrentUserOptional, skip: int = 0, limit: int = 100):
    """List users from the MySQL `users` table. Requires authentication."""
    _require_auth(current_user)
    limit = min(max(0, limit), 500)
    skip = max(0, skip)
    stmt = (
        select(User)
        .order_by(User.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = db.execute(stmt)
    rows = result.scalars().all()
    return [UserResponse.model_validate(u) for u in rows]


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: str, db: DbSession, current_user: CurrentUserOptional):
    """Get user by id. Requires authentication."""
    _require_auth(current_user)
    user = _get_user_or_404(db, user_id)
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(user_id: str, body: UserUpdate, db: DbSession, current_user: CurrentUserOptional):
    """Update user. Only provided fields are updated. Requires authentication."""
    _require_auth(current_user)
    user = _get_user_or_404(db, user_id)
    if body.name is not None:
        user.name = body.name.strip() or user.name
    if body.email is not None:
        existing = db.execute(select(User).where(User.email == body.email, User.id != user_id)).scalars().first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        user.email = body.email
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", response_model=Message)
def delete_user(user_id: str, db: DbSession, current_user: CurrentUserOptional):
    """Deactivate user (soft delete: sets is_active=False). Requires authentication."""
    _require_auth(current_user)
    user = _get_user_or_404(db, user_id)
    user.is_active = False
    db.commit()
    return Message(message="User deactivated")
