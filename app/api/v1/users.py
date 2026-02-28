"""Users API — list, get, update (stubs)."""
from fastapi import APIRouter, HTTPException
from app.api.deps import DbSession

from app.schemas.user import UserResponse
from app.schemas.common import Message

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
def list_users(db: DbSession, skip: int = 0, limit: int = 100):
    """List users. TODO: add auth and pagination."""
    raise NotImplementedError("TODO: implement list users")


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: str, db: DbSession):
    """Get user by id. TODO: add auth."""
    raise NotImplementedError("TODO: implement get user")


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(user_id: str, db: DbSession):
    """Update user. TODO: add auth and body schema."""
    raise NotImplementedError("TODO: implement update user")


@router.delete("/{user_id}", response_model=Message)
def delete_user(user_id: str, db: DbSession):
    """Deactivate or delete user. TODO: add auth."""
    raise NotImplementedError("TODO: implement delete user")
