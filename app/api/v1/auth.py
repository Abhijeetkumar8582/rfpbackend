"""Auth API — login, signup, refresh, logout."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token_pair,
    decode_token,
    hash_refresh_token,
)
from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.models.user import UserRole
from app.schemas.user import UserCreate, UserLogin, UserResponse, TokenResponse, RefreshBody
from app.schemas.common import Message

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse)
def register(body: UserCreate, db: DbSession):
    """Register a new user."""
    existing = db.execute(select(User).where(User.email == body.email)).scalars().one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
        role=UserRole.viewer,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(body: UserLogin, db: DbSession):
    """Login: validate credentials, return access + refresh tokens and user."""
    user = db.execute(select(User).where(User.email == body.email)).scalars().one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is disabled")

    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Account is temporarily locked")

    if not verify_password(body.password, user.password_hash):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        # Optional: lock after 5 failures for 15 minutes
        if user.failed_login_count >= 5:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Success: reset failed login count
    user.failed_login_count = 0
    user.locked_until = None
    db.commit()

    access_token = create_access_token(user.id)
    raw_refresh, token_hash = create_refresh_token_pair(user.id)
    payload = decode_token(raw_refresh)
    expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc) if payload else None
    if not expires_at:
        raise HTTPException(status_code=500, detail="Token creation failed")

    refresh_row = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        created_at=datetime.now(timezone.utc),
    )
    db.add(refresh_row)
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(body: RefreshBody, db: DbSession):
    """Refresh access token using refresh token."""
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    token_hash = hash_refresh_token(body.refresh_token)
    from sqlalchemy import and_
    refresh_row = db.execute(
        select(RefreshToken).where(
            and_(
                RefreshToken.user_id == int(user_id),
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > datetime.now(timezone.utc),
            )
        )
    ).scalars().one_or_none()
    if not refresh_row:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = db.get(User, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    access_token = create_access_token(user.id)
    return TokenResponse(
        access_token=access_token,
        refresh_token=body.refresh_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/logout", response_model=Message)
def logout(body: RefreshBody, db: DbSession):
    """Revoke refresh token."""
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        return Message(message="OK")

    user_id = payload.get("sub")
    token_hash = hash_refresh_token(body.refresh_token)
    if user_id:
        from sqlalchemy import and_
        refresh_row = db.execute(
            select(RefreshToken).where(
                and_(
                    RefreshToken.user_id == int(user_id),
                    RefreshToken.token_hash == token_hash,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        ).scalars().one_or_none()
        if refresh_row:
            refresh_row.revoked_at = datetime.now(timezone.utc)
            db.commit()
    return Message(message="OK")
