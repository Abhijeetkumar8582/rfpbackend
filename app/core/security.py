"""Password hashing and JWT token utilities."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Hash a plain password with bcrypt."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    return pwd_context.verify(plain_password, password_hash)


def _token_hash(token: str) -> str:
    """Produce a stable hash of a token for storage (e.g. refresh token)."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(sub: int | str) -> str:
    """Create a JWT access token with subject (user id) and expiry."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(sub), "exp": expire, "type": "access"}
    return jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token_pair(sub: int | str) -> tuple[str, str]:
    """
    Create a refresh token string and its hash for DB storage.
    Returns (raw_token, token_hash).
    """
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    raw = secrets.token_urlsafe(48)
    payload = {"sub": str(sub), "exp": expire, "type": "refresh", "jti": raw}
    encoded = jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return encoded, _token_hash(encoded)


def decode_token(token: str) -> dict | None:
    """Decode and validate a JWT; return payload or None if invalid."""
    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError:
        return None


def hash_refresh_token(raw_token: str) -> str:
    """Hash a refresh token string for storage/lookup."""
    return _token_hash(raw_token)
