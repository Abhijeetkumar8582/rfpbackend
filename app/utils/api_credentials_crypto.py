"""
AES-256 encryption helpers for storing API credentials in the DB.

We store ciphertext (not plaintext) in api_credentials.secret_key_*.
When we need to call an external API, we decrypt at runtime.

Algorithm:
- AES-256-GCM (authenticated encryption)
- Output token format: base64url( nonce(12) || ciphertext || tag(16) )

Key management:
- Use settings.credentials_encryption_key (env: CREDENTIALS_ENCRYPTION_KEY)
- Recommended: base64 of 32 random bytes (optionally prefixed with "base64:")
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

_NONCE_LEN: Final[int] = 12


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(token: str) -> bytes:
    padded = token + "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def _load_key_32() -> bytes:
    """
    Load/derive a 32-byte key.

    - If env is base64 (optionally with 'base64:' prefix), decode it.
    - If env looks like 64-char hex, decode it.
    - Otherwise derive a stable 32-byte key via SHA-256 of the provided string.
      (Works, but prefer supplying a true random 32-byte key in production.)
    """
    raw = (settings.credentials_encryption_key or "").strip()
    if not raw:
        raise RuntimeError("CREDENTIALS_ENCRYPTION_KEY is not set (needed to encrypt/decrypt api_credentials).")

    if raw.lower().startswith("base64:"):
        raw = raw.split(":", 1)[1].strip()

    # base64 (common for 32 bytes)
    try:
        b = base64.b64decode(raw, validate=True)
        if len(b) == 32:
            return b
    except Exception:
        pass

    # hex (64 chars -> 32 bytes)
    try:
        if len(raw) == 64:
            b = bytes.fromhex(raw)
            if len(b) == 32:
                return b
    except Exception:
        pass

    return hashlib.sha256(raw.encode("utf-8")).digest()


def encrypt_secret(plaintext: str | None, *, aad: str | None = None) -> str | None:
    """
    Encrypt a secret string. Returns a compact base64url token.

    aad: optional additional authenticated data (e.g. tenant_id or api_name) that
         must match on decrypt, preventing ciphertext reuse across contexts.
    """
    if plaintext is None:
        return None
    if plaintext == "":
        return ""

    key = _load_key_32()
    aes = AESGCM(key)
    nonce = os.urandom(_NONCE_LEN)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), (aad or "").encode("utf-8") if aad is not None else None)
    return _b64url_encode(nonce + ct)


def decrypt_secret(token: str | None, *, aad: str | None = None) -> str | None:
    """Decrypt a token produced by encrypt_secret()."""
    if token is None:
        return None
    if token == "":
        return ""

    raw = _b64url_decode(token)
    if len(raw) < _NONCE_LEN + 16:
        raise ValueError("Invalid encrypted secret token.")

    nonce = raw[:_NONCE_LEN]
    ct = raw[_NONCE_LEN:]
    key = _load_key_32()
    aes = AESGCM(key)
    pt = aes.decrypt(nonce, ct, (aad or "").encode("utf-8") if aad is not None else None)
    return pt.decode("utf-8")

