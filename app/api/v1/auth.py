"""Auth API — login, refresh, logout, invite completion."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

logger = logging.getLogger(__name__)


def _utc(dt: datetime | None) -> datetime | None:
    """Normalize to UTC for comparison. MySQL may return naive or session-timezone datetimes."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

from app.api.deps import DbSession
from app.services.activity_log import log_activity
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token_pair,
    decode_token,
    decode_invite_token,
    hash_refresh_token,
)
from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.models.user_invite import UserInvite
from app.schemas.user import UserLogin, UserResponse, TokenResponse, RefreshBody
from app.schemas.invite import InviteValidateResponse, InviteCompleteRequest
from app.schemas.common import Message

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(request: Request, body: UserLogin, db: DbSession):
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

    # Record login in activity log (server-side so it appears even if frontend fails)
    try:
        client_host = request.client.host if request and request.client else None
        log_activity(
            db,
            actor=user.name or user.email or "User",
            event_action="Login",
            target_resource="Platform",
            severity="info",
            ip_address=client_host,
            system="web",
        )
    except Exception:
        pass  # non-blocking; don't fail login if activity_logs table missing or write fails

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

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user_id = user_id_raw

    token_hash = hash_refresh_token(body.refresh_token)
    from sqlalchemy import and_
    refresh_row = db.execute(
        select(RefreshToken).where(
            and_(
                RefreshToken.user_id == user_id,
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > datetime.now(timezone.utc),
            )
        )
    ).scalars().one_or_none()
    if not refresh_row:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = db.get(User, user_id)
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

    user_id_raw = payload.get("sub")
    token_hash = hash_refresh_token(body.refresh_token)
    if user_id_raw:
        user_id = user_id_raw
        if user_id:
            from sqlalchemy import and_
            refresh_row = db.execute(
                select(RefreshToken).where(
                    and_(
                        RefreshToken.user_id == user_id,
                        RefreshToken.token_hash == token_hash,
                        RefreshToken.revoked_at.is_(None),
                    )
                )
            ).scalars().one_or_none()
            if refresh_row:
                refresh_row.revoked_at = datetime.now(timezone.utc)
                db.commit()
    return Message(message="OK")


@router.get("/invite/validate", response_model=InviteValidateResponse)
def validate_invite(token: str, db: DbSession):
    """
    Validate an invite JWT (unauthenticated). Verifies signature and exp, then checks DB for one-time use/revocation.

    Returns safe user info if valid, 400 if invalid/expired/used.
    """
    payload = decode_invite_token(token)
    if not payload:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")

    invite = db.execute(
        select(UserInvite).where(
            UserInvite.token == token,
            UserInvite.revoked.is_(False),
        )
    ).scalars().one_or_none()
    if not invite or invite.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")

    # Return email/name from JWT payload (already verified)
    exp_ts = payload.get("exp")
    expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc) if exp_ts else invite.expires_at
    return InviteValidateResponse(
        email=payload["email"],
        name=payload.get("name") or "",
        expires_at=expires_at,
    )


@router.post("/invite/complete", response_model=TokenResponse)
def complete_invite(body: InviteCompleteRequest, request: Request, db: DbSession):
    """
    Complete invite flow: verify invite JWT, set password, activate user, mark invite used,
    and issue normal login tokens.
    """
    payload = decode_invite_token(body.token)
    if not payload:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")

    invite = db.execute(
        select(UserInvite).where(
            UserInvite.token == body.token,
            UserInvite.revoked.is_(False),
        )
    ).scalars().one_or_none()
    if not invite or invite.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")

    user = db.get(User, invite.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid invite token")

    now = datetime.now(timezone.utc)
    # Set password and activate account
    user.password_hash = hash_password(body.new_password)
    user.is_active = True
    invite.used_at = now

    # Optionally, mark other unused invites for this user as revoked
    others = db.execute(
        select(UserInvite).where(
            UserInvite.user_id == user.id,
            UserInvite.id != invite.id,
            UserInvite.used_at.is_(None),
            UserInvite.revoked.is_(False),
        )
    ).scalars().all()
    for other in others:
        other.revoked = True

    db.commit()

    # Issue normal login tokens so frontend can auto-sign-in
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
        created_at=now,
    )
    db.add(refresh_row)
    db.commit()

    # Log invite completion as a login-like event
    try:
        client_host = request.client.host if request and request.client else None
        log_activity(
            db,
            actor=user.name or user.email or "User",
            event_action="InviteCompleted",
            target_resource="Platform",
            severity="info",
            ip_address=client_host,
            system="web",
        )
    except Exception:
        pass

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )

