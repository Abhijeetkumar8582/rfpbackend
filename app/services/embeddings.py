"""OpenAI embeddings — store vector in SQL for similarity / cluster view."""
from __future__ import annotations

import json

from app.config import settings


def get_embedding(text: str) -> list[float]:
    """
    Get embedding vector for text using OpenAI. Returns list of floats.
    Store as JSON string in document.embedding_json for vector similarity.
    """
    if not text or not text.strip():
        text = " "  # OpenAI requires non-empty
    text = text[:8_000]  # token limit for text-embedding-3-small

    if not settings.openai_api_key:
        raise ValueError("OpenAI API key not configured (set OPENAI_API_KEY in .env)")

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.embeddings.create(
        model=settings.openai_embedding_model,
        input=text,
    )
    return resp.data[0].embedding


def embedding_to_json(embedding: list[float]) -> str:
    """Serialize embedding for DB storage."""
    return json.dumps(embedding)
