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


def _role_label_to_enum(label: str) -> UserRole:
    """Map UI labels to UserRole: Super Admin -> admin, Admin -> manager, Developer -> analyst, Viewer -> viewer."""
    s = (label or "").strip().lower()
    if s in ("super admin", "superadmin"):
        return UserRole.admin
    if s == "admin":
        return UserRole.manager
    if s == "developer":
        return UserRole.analyst
    if s == "viewer":
        return UserRole.viewer
    raise ValueError("invalid role")


class UserUpdate(BaseModel):
    """Optional fields for PATCH /users/{user_id}. Only provided fields are updated. Role accepts enum value or UI label (Super Admin, Admin, Developer, Viewer)."""
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
        s = str(v).strip().lower()
        for r in UserRole:
            if r.value == s:
                return r
        return _role_label_to_enum(str(v))


class UserResponse(BaseModel):
    """Matches MySQL users table: id, email, name, role, is_active, created_at (no password_hash)."""
    id: str
    email: str
    name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    vector_database: str | None = None

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


class CollaborationUserOut(BaseModel):
    """Minimal user fields for RFP collaborator picker (id, name, email)."""

    id: str
    name: str
    email: str


class UserVectorDatabaseResponse(BaseModel):
    """After provisioning, Qdrant collection name stored on the user as vector_database."""

    vector_database: str
    message: str = "Vector database collection is ready."


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshBody(BaseModel):
    refresh_token: str
