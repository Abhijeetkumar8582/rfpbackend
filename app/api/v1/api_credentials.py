"""API Credentials — encrypted storage for external provider configs."""

from __future__ import annotations

import json
import uuid
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
import httpx

from app.api.deps import CurrentUserOptional, DbSession, require_admin_only
from app.utils.api_credentials_crypto import decrypt_secret, encrypt_secret
from app.services.openai_client import build_chat_completions_body

router = APIRouter(prefix="/api-credentials", tags=["api-credentials"])

DEFAULT_ORG_ID = "1000"


class _Group(BaseModel):
    baseUrl: str = ""
    apiKey: str = ""
    model: str = ""


class OpenAIConfig(BaseModel):
    chat: _Group = Field(default_factory=_Group)
    embedding: _Group = Field(default_factory=_Group)
    ocr: _Group = Field(default_factory=_Group)

class TestRequest(BaseModel):
    baseUrl: str = ""
    apiKey: str = ""
    model: str = ""


class TestResult(BaseModel):
    ok: bool
    status_code: int | None = None
    latency_ms: int | None = None
    message: str = ""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _auth_headers(api_key: str) -> dict:
    api_key = (api_key or "").strip()
    if not api_key:
        return {}
    # OpenAI-compatible gateways generally accept Bearer.
    return {"Authorization": f"Bearer {api_key}"}


def _safe_url(url: str) -> str:
    return (url or "").strip()

def _mask_secret(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if len(s) <= 6:
        return "*" * len(s)
    return f"{s[:3]}…{s[-3:]}"


def _looks_masked(s: str) -> bool:
    s = (s or "").strip()
    return "…" in s or "..." in s


def _get_active_row(db: DbSession, tenant_id: str, api_name: str):
    return db.execute(
        text(
            """
            SELECT api_url, secret_key_1, secret_key_2, secret_key_3, parameter_json
            FROM api_credentials
            WHERE tenant_id = :tenant_id AND api_name = :api_name AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "api_name": api_name},
    ).mappings().one_or_none()


def _resolve_api_key_from_db(db: DbSession, tenant_id: str, api_name: str, which: int) -> str:
    row = _get_active_row(db, tenant_id, api_name)
    if not row:
        return ""
    aad = f"{tenant_id}:{api_name}"
    col = {1: "secret_key_1", 2: "secret_key_2", 3: "secret_key_3"}.get(which)
    if not col:
        return ""
    try:
        return decrypt_secret(row.get(col) or "", aad=aad) or ""
    except Exception:
        return ""


def _require_test_inputs(body: TestRequest, label: str):
    if not body.baseUrl.strip():
        raise HTTPException(status_code=400, detail=f"{label}: Base URL is required")
    if not body.model.strip():
        raise HTTPException(status_code=400, detail=f"{label}: Model is required")


@router.post("/openai/test/chat", response_model=TestResult)
def test_openai_chat(body: TestRequest, db: DbSession, current_user: CurrentUserOptional):
    """Test Chat API (admin only). Does not save anything."""
    require_admin_only(current_user)
    _require_test_inputs(body, "Chat")
    tenant_id = DEFAULT_ORG_ID
    api_key = body.apiKey.strip()
    if (not api_key) or _looks_masked(api_key):
        api_key = _resolve_api_key_from_db(db, tenant_id, "openai", 1)
    if not api_key:
        raise HTTPException(status_code=400, detail="Chat: API Key is required (set it or save one first).")

    url = _safe_url(body.baseUrl)
    payload = build_chat_completions_body(
        model=body.model.strip(),
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=1,
        send_model_in_body=True,
    )

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=20.0) as client:
            res = client.post(url, headers={"Content-Type": "application/json", **_auth_headers(api_key)}, json=payload)
        ms = int((time.perf_counter() - t0) * 1000)
        if 200 <= res.status_code < 300:
            return TestResult(ok=True, status_code=res.status_code, latency_ms=ms, message="Chat test OK")
        return TestResult(ok=False, status_code=res.status_code, latency_ms=ms, message=(res.text or "Chat test failed")[:400])
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        return TestResult(ok=False, latency_ms=ms, message=str(e)[:400])


@router.post("/openai/test/embedding", response_model=TestResult)
def test_openai_embedding(body: TestRequest, db: DbSession, current_user: CurrentUserOptional):
    """Test Embeddings API (admin only). Does not save anything."""
    require_admin_only(current_user)
    _require_test_inputs(body, "Embedding")
    tenant_id = DEFAULT_ORG_ID
    api_key = body.apiKey.strip()
    if (not api_key) or _looks_masked(api_key):
        api_key = _resolve_api_key_from_db(db, tenant_id, "openai", 2)
    if not api_key:
        raise HTTPException(status_code=400, detail="Embedding: API Key is required (set it or save one first).")

    url = _safe_url(body.baseUrl)
    payload = {
        "model": body.model.strip(),
        "input": "ping",
    }

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=20.0) as client:
            res = client.post(url, headers={"Content-Type": "application/json", **_auth_headers(api_key)}, json=payload)
        ms = int((time.perf_counter() - t0) * 1000)
        if 200 <= res.status_code < 300:
            return TestResult(ok=True, status_code=res.status_code, latency_ms=ms, message="Embedding test OK")
        return TestResult(ok=False, status_code=res.status_code, latency_ms=ms, message=(res.text or "Embedding test failed")[:400])
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        return TestResult(ok=False, latency_ms=ms, message=str(e)[:400])


@router.post("/openai/test/ocr", response_model=TestResult)
def test_openai_ocr(body: TestRequest, db: DbSession, current_user: CurrentUserOptional):
    """
    Test OCR API (admin only).
    Many OCR setups are just chat-completions w/ vision, but we keep this as a lightweight
    "chat-style" connectivity test (no image upload) to validate baseUrl + key + model.
    """
    require_admin_only(current_user)
    _require_test_inputs(body, "OCR")
    tenant_id = DEFAULT_ORG_ID
    api_key = body.apiKey.strip()
    if (not api_key) or _looks_masked(api_key):
        api_key = _resolve_api_key_from_db(db, tenant_id, "openai", 3)
    if not api_key:
        raise HTTPException(status_code=400, detail="OCR: API Key is required (set it or save one first).")

    url = _safe_url(body.baseUrl)
    payload = build_chat_completions_body(
        model=body.model.strip(),
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=1,
        send_model_in_body=True,
    )

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=20.0) as client:
            res = client.post(url, headers={"Content-Type": "application/json", **_auth_headers(api_key)}, json=payload)
        ms = int((time.perf_counter() - t0) * 1000)
        if 200 <= res.status_code < 300:
            return TestResult(ok=True, status_code=res.status_code, latency_ms=ms, message="OCR test OK")
        return TestResult(ok=False, status_code=res.status_code, latency_ms=ms, message=(res.text or "OCR test failed")[:400])
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        return TestResult(ok=False, latency_ms=ms, message=str(e)[:400])


@router.get("/openai", response_model=OpenAIConfig)
def get_openai_config(db: DbSession, current_user: CurrentUserOptional):
    """Load OpenAI config for current tenant (admin only). Returns masked keys (never plaintext)."""
    require_admin_only(current_user)
    # TODO: replace with real organization/tenant id once org model exists.
    tenant_id = DEFAULT_ORG_ID
    api_name = "openai"

    row = _get_active_row(db, tenant_id, api_name)

    if not row:
        return OpenAIConfig()

    params = {}
    if row.get("parameter_json"):
        try:
            params = row["parameter_json"] if isinstance(row["parameter_json"], dict) else json.loads(row["parameter_json"])
        except Exception:
            params = {}

    aad = f"{tenant_id}:{api_name}"
    return OpenAIConfig(
        chat=_Group(
            baseUrl=(params.get("chat", {}) or {}).get("baseUrl", ""),
            apiKey=_mask_secret(decrypt_secret(row.get("secret_key_1") or "", aad=aad) or ""),
            model=(params.get("chat", {}) or {}).get("model", ""),
        ),
        embedding=_Group(
            baseUrl=(params.get("embedding", {}) or {}).get("baseUrl", ""),
            apiKey=_mask_secret(decrypt_secret(row.get("secret_key_2") or "", aad=aad) or ""),
            model=(params.get("embedding", {}) or {}).get("model", ""),
        ),
        ocr=_Group(
            baseUrl=(params.get("ocr", {}) or {}).get("baseUrl", ""),
            apiKey=_mask_secret(decrypt_secret(row.get("secret_key_3") or "", aad=aad) or ""),
            model=(params.get("ocr", {}) or {}).get("model", ""),
        ),
    )


@router.put("/openai", response_model=dict)
def upsert_openai_config(body: OpenAIConfig, db: DbSession, current_user: CurrentUserOptional):
    """Create/update OpenAI config for current tenant (admin only). Encrypts keys at rest."""
    require_admin_only(current_user)
    # TODO: replace with real organization/tenant id once org model exists.
    tenant_id = DEFAULT_ORG_ID
    api_name = "openai"

    aad = f"{tenant_id}:{api_name}"
    existing = _get_active_row(db, tenant_id, api_name)

    def _enc_or_keep(new_val: str, which: int) -> str | None:
        new_val = (new_val or "").strip()
        if (not new_val) or _looks_masked(new_val):
            if not existing:
                return None
            return existing.get({1: "secret_key_1", 2: "secret_key_2", 3: "secret_key_3"}[which])
        return encrypt_secret(new_val, aad=aad)

    enc1 = _enc_or_keep(body.chat.apiKey, 1)
    enc2 = _enc_or_keep(body.embedding.apiKey, 2)
    enc3 = _enc_or_keep(body.ocr.apiKey, 3)

    params = {
        "chat": {"baseUrl": body.chat.baseUrl, "model": body.chat.model},
        "embedding": {"baseUrl": body.embedding.baseUrl, "model": body.embedding.model},
        "ocr": {"baseUrl": body.ocr.baseUrl, "model": body.ocr.model},
    }
    params_json = json.dumps(params)

    # Upsert in a DB-portable way: try update, if nothing updated then insert.
    updated = db.execute(
        text(
            """
            UPDATE api_credentials
            SET
              api_url = :api_url,
              secret_key_1 = :secret_key_1,
              secret_key_2 = :secret_key_2,
              secret_key_3 = :secret_key_3,
              parameter_json = :parameter_json,
              status = 'active',
              updated_at = :updated_at
            WHERE tenant_id = :tenant_id AND api_name = :api_name
            """
        ),
        {
            "api_url": None,
            "secret_key_1": enc1,
            "secret_key_2": enc2,
            "secret_key_3": enc3,
            "parameter_json": params_json,
            "updated_at": _now_utc(),
            "tenant_id": tenant_id,
            "api_name": api_name,
        },
    ).rowcount

    if not updated:
        try:
            db.execute(
                text(
                    """
                    INSERT INTO api_credentials
                      (id, tenant_id, api_name, api_url, secret_key_1, secret_key_2, secret_key_3, parameter_json, status, created_at, updated_at)
                    VALUES
                      (:id, :tenant_id, :api_name, :api_url, :secret_key_1, :secret_key_2, :secret_key_3, :parameter_json, 'active', :created_at, :updated_at)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "api_name": api_name,
                    "api_url": None,
                    "secret_key_1": enc1,
                    "secret_key_2": enc2,
                    "secret_key_3": enc3,
                    "parameter_json": params_json,
                    "created_at": _now_utc(),
                    "updated_at": _now_utc(),
                },
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save credentials: {e}")

    db.commit()
    return {"message": "Saved"}

