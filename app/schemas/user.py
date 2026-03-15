"""User and auth schemas."""
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator

from app.models.user import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    remember: bool = False


class UserUpdate(BaseModel):
    """Optional fields for PATCH /users/{user_id}. Only provided fields are updated."""
    name: str | None = None
    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None

    @field_validator("role", mode="before")
    @classmethod
    def coerce_role(cls, v):
        if v is None:
            return None
        if isinstance(v, UserRole):
            return v
        s = str(v).lower().strip()
        for r in UserRole:
            if r.value == s:
                return r
        raise ValueError("invalid role")


class UserResponse(BaseModel):
    """Matches MySQL users table: id, email, name, role, is_active, created_at (no password_hash)."""
    id: str
    email: str
    name: str
    role: UserRole
    is_active: bool
    created_at: datetime

    @field_validator("is_active", mode="before")
    @classmethod
    def coerce_is_active(cls, v):
        """MySQL returns 0/1 for BOOLEAN; coerce to bool."""
        if v is None:
            return True
        if isinstance(v, bool):
            return v
        return bool(int(v))

    @field_validator("role", mode="before")
    @classmethod
    def coerce_role(cls, v):
        """Accept role as string from DB (e.g. 'viewer') or UserRole enum."""
        if v is None:
            return UserRole.viewer
        if isinstance(v, UserRole):
            return v
        s = str(v).lower().strip()
        for r in UserRole:
            if r.value == s:
                return r
        return UserRole.viewer

    @field_validator("created_at", mode="before")
    @classmethod
    def coerce_created_at(cls, v):
        """Accept created_at as string from MySQL (e.g. '2026-02-19 21:35:27') or datetime."""
        if v is None:
            return datetime.now()
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            try:
                return datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00"))
                except ValueError:
                    pass
        return v

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshBody(BaseModel):
    refresh_token: str
