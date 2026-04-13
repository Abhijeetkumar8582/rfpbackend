"""Users API — list, get, update, delete, invite."""
from datetime import datetime, timedelta, timezone
import logging
import secrets

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, update

from app.api.deps import DbSession, CurrentUser, CurrentUserOptional
from app.config import settings
from app.core.security import hash_password, create_invite_token
from app.core.user_id import generate_user_id
from app.models.user import User, UserRole
from app.models.user_kb_settings import UserKbSettings
from app.models.user_invite import UserInvite
from app.models.search_query import SearchQuery
from app.models.document import Document
from app.models.audit_log import AuditLog
from app.schemas.user import CollaborationUserOut, UserResponse, UserUpdate, UserVectorDatabaseResponse
from app.schemas.search import SearchBalance
from app.services.embeddings import is_embedding_configured
from app.services.qdrant import provision_user_vector_database
from app.schemas.invite import UserInviteCreate, UserInviteCreatedResponse
from app.schemas.common import Message
from app.services.email import send_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


def _require_auth(current_user: CurrentUserOptional):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")


def _require_admin_or_manager(current_user: CurrentUserOptional):
    """Only superadmin (admin) or admin (manager) can create/delete users."""
    _require_auth(current_user)
    if current_user.role not in (UserRole.admin, UserRole.manager):
        raise HTTPException(
            status_code=403,
            detail="Only Super Admin or Admin can create or delete users.",
        )


def _get_user_or_404(db: DbSession, user_id: str) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/me/vector-database", response_model=UserVectorDatabaseResponse)
def ensure_my_vector_database(db: DbSession, current_user: CurrentUser):
    """
    Create a dedicated Qdrant collection for the current user (name derived from their display name
    and user id) and save the collection name on the user as `vector_database`.
    Idempotent: safe to call again; reuses the stored collection name when already set.
    Requires embedding API configuration (same as document indexing) to determine vector size.
    """
    if not is_embedding_configured():
        raise HTTPException(
            status_code=503,
            detail="Embedding API not configured. Set OPENAI_API_KEY and OPENAI_BASE_URL (or OPENAI_EMBEDDING_BASE_URL) to provision a vector database.",
        )
    user = db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    name = provision_user_vector_database(user.id, user.name, user.vector_database)
    user.vector_database = name
    db.commit()
    db.refresh(user)
    return UserVectorDatabaseResponse(vector_database=name)


_DEFAULT_KB_SETTINGS = SearchBalance(text_pct=30, vector_pct=60, rerank_pct=10)


@router.get("/me/kb-settings", response_model=SearchBalance)
def get_my_kb_settings(db: DbSession, current_user: CurrentUser):
    """
    Search balance (Text / Vector / Rerank %) for the RFP Assistant.
    Returns defaults until the user saves preferences via PUT.
    """
    row = db.get(UserKbSettings, current_user.id)
    if not row:
        return _DEFAULT_KB_SETTINGS
    return SearchBalance(text_pct=row.text_pct, vector_pct=row.vector_pct, rerank_pct=row.rerank_pct)


@router.put("/me/kb-settings", response_model=SearchBalance)
def put_my_kb_settings(body: SearchBalance, db: DbSession, current_user: CurrentUser):
    """Persist Search balance weights for the current user."""
    now = datetime.now(timezone.utc)
    row = db.get(UserKbSettings, current_user.id)
    if row:
        row.text_pct = body.text_pct
        row.vector_pct = body.vector_pct
        row.rerank_pct = body.rerank_pct
        row.updated_at = now
    else:
        db.add(
            UserKbSettings(
                user_id=current_user.id,
                text_pct=body.text_pct,
                vector_pct=body.vector_pct,
                rerank_pct=body.rerank_pct,
                updated_at=now,
            )
        )
    db.commit()
    return body


def _map_role_label_to_enum(label: str) -> UserRole:
    """
    Map human-friendly role label from UI to internal UserRole enum.

    - "Super Admin" -> UserRole.admin
    - "Admin" -> UserRole.manager
    - "Developer" -> UserRole.analyst
    - "Viewer" -> UserRole.viewer
    """
    s = (label or "").strip().lower()
    if s == "super admin":
        return UserRole.admin
    if s == "admin":
        return UserRole.manager
    if s == "developer":
        return UserRole.analyst
    return UserRole.viewer


@router.get("/collaboration-directory", response_model=list[CollaborationUserOut])
def collaboration_directory(
    db: DbSession,
    current_user: CurrentUser,
    limit: int = Query(200, ge=1, le=500),
):
    """List active users (except self) for adding RFP collaborators. Any authenticated user."""
    stmt = (
        select(User)
        .where(User.is_active.is_(True), User.id != current_user.id)
        .order_by(User.name.asc(), User.email.asc())
        .limit(limit)
    )
    rows = db.execute(stmt).scalars().all()
    return [CollaborationUserOut(id=u.id, name=u.name or "", email=u.email or "") for u in rows]


@router.get("", response_model=list[UserResponse])
def list_users(db: DbSession, current_user: CurrentUserOptional, skip: int = 0, limit: int = 100):
    """List users from the MySQL `users` table. Super Admin or Admin only (Team Directory)."""
    _require_admin_or_manager(current_user)
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
    """Get user by id. Super Admin or Admin only (Team Directory)."""
    _require_admin_or_manager(current_user)
    user = _get_user_or_404(db, user_id)
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(user_id: str, body: UserUpdate, db: DbSession, current_user: CurrentUserOptional):
    """Update user (edit). Only provided fields are updated. Role can only be changed by Super Admin or Admin. Requires authentication."""
    _require_auth(current_user)
    user = _get_user_or_404(db, user_id)
    if body.name is not None:
        user.name = (body.name or "").strip() or user.name
    if body.email is not None:
        existing = db.execute(select(User).where(User.email == body.email, User.id != user_id)).scalars().first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        user.email = body.email
    if body.role is not None:
        _require_admin_or_manager(current_user)
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", response_model=Message)
def delete_user(
    user_id: str,
    db: DbSession,
    current_user: CurrentUserOptional,
    permanent: bool = Query(False, description="If true, permanently remove the user from the database; otherwise soft delete (deactivate)."),
):
    """
    Delete user. Only Super Admin or Admin. Requires authentication.

    - **Soft delete (default)**: Sets is_active=False; user can be reactivated via PATCH.
    - **Permanent (permanent=true)**: Removes the user row. Linked records
      (documents, audit logs, search queries) are kept with the user reference set to NULL.
    """
    _require_admin_or_manager(current_user)
    user = _get_user_or_404(db, user_id)

    if not permanent:
        user.is_active = False
        db.commit()
        return Message(message="User deactivated")

    # Hard delete: nullify all nullable FKs that reference this user, then delete the row.
    # Related records (documents, audit logs, search queries) are kept with uploader set to NULL.
    try:
        db.execute(update(Document).where(Document.uploaded_by == user_id).values(uploaded_by=None))
        db.execute(update(SearchQuery).where(SearchQuery.actor_user_id == user_id).values(actor_user_id=None))
        db.execute(update(AuditLog).where(AuditLog.actor_user_id == user_id).values(actor_user_id=None))
        db.delete(user)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Failed to permanently delete user %s", user_id)
        raise HTTPException(
            status_code=500,
            detail="Failed to delete user. Please try again.",
        ) from e
    return Message(message="User permanently deleted")


@router.post("/invite", response_model=UserInviteCreatedResponse)
def create_user_invite(body: UserInviteCreate, db: DbSession, current_user: CurrentUserOptional):
    """
    Create a new user via invite. Only Super Admin or Admin.

    - Validate payload (email, name, role).
    - Generate a strong random password and hash it.
    - Insert user row with is_active=False.
    - Create a one-time invite token row.
    - Send email with Verify & Set Password link.
    """
    _require_admin_or_manager(current_user)

    existing = db.execute(select(User).where(User.email == body.email)).scalars().one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    now = datetime.now(timezone.utc)

    # Random password that is never shown to anyone.
    random_password = secrets.token_urlsafe(32)
    password_hash = hash_password(random_password)

    role_enum = _map_role_label_to_enum(body.role)

    user = User(
        id=generate_user_id(),
        email=body.email,
        name=body.name,
        password_hash=password_hash,
        role=role_enum,
        is_active=False,
        created_at=now,
    )
    db.add(user)
    db.flush()

    # Create invite JWT (payload: sub, email, name, exp) and store it in invite row
    expires_at = now + timedelta(hours=max(1, settings.invite_token_hours))
    token = create_invite_token(
        user_id=user.id,
        email=body.email,
        name=body.name,
        expires_at=expires_at,
    )
    invite = UserInvite(
        user_id=user.id,
        token=token,
        expires_at=expires_at,
        used_at=None,
        created_at=now,
        revoked=False,
    )
    db.add(invite)
    db.commit()

    # Build invite email (use localhost when placeholder or unset)
    _base = (settings.frontend_base_url or "").strip().rstrip("/")
    if not _base or "yourdomain.com" in _base.lower():
        _base = "http://localhost:3000"
    invite_url = f"{_base}/set-password?token={token}"
    product_name = settings.product_name or "RFP Platform"
    subject = f"You've been invited to {product_name}"

    plain = (
        f"Hi {body.name},\n\n"
        f"You've been invited to {product_name}. To verify your email and set your password, "
        f"please open the link below:\n\n{invite_url}\n\n"
        "If you did not expect this invitation, you can safely ignore this email.\n"
    )

    html = f"""
<html>
  <body style="background-color:#f3f4f6;margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
      <tr>
        <td align="center">
          <table width="600" cellpadding="0" cellspacing="0" role="presentation" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 10px 30px rgba(15,23,42,0.15);">
            <tr>
              <td style="padding:24px 32px 16px 32px;background:linear-gradient(135deg,#0f172a,#1d4ed8);color:#e5e7eb;">
                <div style="font-size:18px;font-weight:600;">{product_name}</div>
                <div style="font-size:13px;margin-top:4px;opacity:0.85;">Secure access to your RFP workspace</div>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 8px 32px;color:#0f172a;">
                <h1 style="margin:0 0 12px 0;font-size:22px;font-weight:600;">You’ve been invited</h1>
                <p style="margin:0 0 8px 0;font-size:14px;line-height:1.6;">
                  Hi <strong>{body.name}</strong>,
                </p>
                <p style="margin:0 0 16px 0;font-size:14px;line-height:1.6;">
                  You’ve been invited to join <strong>{product_name}</strong>. To activate your account,
                  please verify your email and set a password.
                </p>
                <p style="margin:0 0 24px 0;font-size:14px;line-height:1.6;">
                  This link is valid for <strong>{max(1, settings.invite_token_hours)} hours</strong> and can be used only once.
                </p>
                <p style="text-align:center;margin:0 0 24px 0;">
                  <a href="{invite_url}"
                     style="display:inline-block;background:#2563eb;color:#ffffff !important;text-decoration:none;padding:12px 28px;border-radius:999px;font-size:14px;font-weight:600;box-shadow:0 8px 20px rgba(37,99,235,0.35);">
                    Verify &amp; Set Password
                  </a>
                </p>
                <p style="margin:0 0 8px 0;font-size:13px;line-height:1.6;color:#4b5563;">
                  If the button above doesn’t work, copy and paste this URL into your browser:
                </p>
                <p style="margin:0 0 16px 0;font-size:12px;line-height:1.6;color:#1d4ed8;word-break:break-all;">
                  <a href="{invite_url}" style="color:#1d4ed8;text-decoration:underline;">{invite_url}</a>
                </p>
                <p style="margin:0 0 4px 0;font-size:11px;line-height:1.6;color:#6b7280;">
                  For your security, this email was sent for account invitation only.
                  If you didn’t expect this, you can safely ignore it.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 32px 20px 32px;font-size:11px;color:#9ca3af;border-top:1px solid #e5e7eb;text-align:center;">
                &copy; {datetime.now(timezone.utc).year} {product_name}. All rights reserved.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
""".strip()

    email_sent = send_email(
        to_emails=[body.email],
        subject=subject,
        plain_content=plain,
        html_content=html,
    )
    if not email_sent:
        logger.warning(
            "Invite created for user_id=%s email=%s but invite email was not sent; check SendGrid config and server logs.",
            user.id,
            body.email,
        )

    return UserInviteCreatedResponse(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        invited_at=now,
        email_sent=email_sent,
    )

