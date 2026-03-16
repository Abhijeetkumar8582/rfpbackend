"""Schemas for user invitation and password setup."""
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.user import UserRole


class UserInviteCreate(BaseModel):
    """Payload for POST /users/invite from Team Directory."""

    name: str = Field(..., description="Full name")
    email: EmailStr
    username: str | None = Field(None, description="UI username (not stored separately in DB)")
    role: str = Field("Viewer", description="Human-friendly role label from UI")
    phone: str | None = None
    timezone: str | None = None
    language: str | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name is required")
        return v

    @field_validator("role")
    @classmethod
    def normalize_role(cls, v: str) -> str:
        return (v or "").strip()


class UserInviteCreatedResponse(BaseModel):
    """Response after creating a user invite (minimal, no token)."""

    user_id: str
    email: EmailStr
    name: str
    role: UserRole
    invited_at: datetime
    email_sent: bool = False  # True if invite email was sent successfully


class InviteValidateResponse(BaseModel):
    """Response for GET /auth/invite/validate."""

    email: EmailStr
    name: str
    expires_at: datetime


class InviteCompleteRequest(BaseModel):
    """Payload for POST /auth/invite/complete."""

    token: str = Field(..., min_length=16)
    new_password: str = Field(..., min_length=8, max_length=256)

