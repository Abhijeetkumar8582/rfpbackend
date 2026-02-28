"""OpenAI embeddings — store vector in SQL for similarity / cluster view."""
from __future__ import annotations

import json

from app.config import settings


def _embeddings_url() -> str:
    """
    Return the URL for the embeddings API. Use OPENAI_EMBEDDING_BASE_URL if set;
    otherwise derive from OPENAI_BASE_URL (chat URL) by replacing path to embeddings.
    """
    base = (settings.openai_embedding_base_url or "").strip()
    if base:
        return base.rstrip("/")
    chat_url = (settings.openai_base_url or "").strip()
    if not chat_url:
        raise ValueError("OPENAI_BASE_URL or OPENAI_EMBEDDING_BASE_URL is required for embeddings")
    # OPENAI_BASE_URL is chat completions (e.g. .../deployments/gpt-4o-mini/chat/completions?api-version=...)
    # Derive embeddings URL: .../deployments/<embedding_model>/embeddings?api-version=...
    url = chat_url.replace("/chat/completions", "/embeddings")
    chat_model = (settings.openai_chat_model or "gpt-4o-mini").strip()
    embed_model = (settings.openai_embedding_model or "text-embedding-3-small").strip()
    if chat_model and embed_model and chat_model != embed_model:
        url = url.replace(f"/{chat_model}/", f"/{embed_model}/")
    return url.rstrip("/")


def _embeddings_token() -> str:
    """Return the API key for embeddings: OPENAI_EMBEDDING_API_KEY if set, else OPENAI_API_KEY."""
    token = (settings.openai_embedding_api_key or "").strip()
    if token:
        return token
    token = (settings.openai_api_key or "").strip()
    if token:
        return token
    raise ValueError(
        "Embedding API key not configured. Set OPENAI_EMBEDDING_API_KEY (for embeddings) or "
        "OPENAI_API_KEY (shared) in .env."
    )


def get_embedding(text: str) -> list[float]:
    """
    Get embedding vector for text.
    Uses OPENAI_EMBEDDING_BASE_URL + OPENAI_EMBEDDING_API_KEY when set (separate from chat).
    Otherwise derives URL from OPENAI_BASE_URL and uses OPENAI_API_KEY.
    """
    if not text or not text.strip():
        text = " "  # OpenAI requires non-empty
    text = text[:8_000]  # token limit for text-embedding-3-small

    import httpx

    url = _embeddings_url()
    bearer = _embeddings_token()
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Content-Type": "application/json",
    }
    body = {
        "input": text,
        "model": settings.openai_embedding_model,
    }
    with httpx.Client() as client:
        resp = client.post(url, headers=headers, json=body, timeout=60.0)
    resp.raise_for_status()
    data = resp.json()
    # OpenAI embeddings response: { "data": [ { "embedding": [...] } ] }
    items = data.get("data") or []
    if not items or "embedding" not in items[0]:
        raise ValueError("Invalid embeddings response: missing data[0].embedding")
    return items[0]["embedding"]


def embedding_to_json(embedding: list[float]) -> str:
    """Serialize embedding for DB storage."""
    return json.dumps(embedding)
