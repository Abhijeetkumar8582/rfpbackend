"""Generate a natural-language answer from search results using GPT (RAG).

Uses OPENAI_BASE_URL and OPENAI_API_KEY from .env (e.g. Druid gateway URL and token).
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Max chars for the user message sent to GPT (some gateways 400 on very large payloads)
_MAX_USER_CONTENT_CHARS = 8000


def _sanitize_text(s: str) -> str:
    """Ensure text is valid for JSON/API: no null bytes, valid UTF-8."""
    if not s:
        return ""
    # Replace null bytes and other control chars that can break gateways
    s = s.replace("\x00", " ")
    try:
        return s.encode("utf-8", errors="replace").decode("utf-8")
    except Exception:
        return ""


def answer_from_chunks(question: str, chunks: list[dict]) -> tuple[str, str | None]:
    """
    Use GPT to synthesize a concise answer from the given question and retrieved chunks.
    chunks: list of {content, filename, score} (or at least content).
    Returns (answer, topic). Topic is None (caller may use a default).

    Uses OPENAI_BASE_URL and OPENAI_API_KEY from .env for the chat completions request.
    """
    if not chunks:
        return "No relevant passages were found. Try rephrasing your question or adding more documents to this project.", None

    url = (settings.openai_base_url or "").strip()
    token = (settings.openai_api_key or "").strip()
    if not url or not token:
        raise RuntimeError(
            "OPENAI_BASE_URL and OPENAI_API_KEY are required for search answer. "
            "Set them in backend/.env (e.g. Druid gateway URL and token)."
        )

    context_parts = []
    total_len = 0
    max_context = 6000
    for i, c in enumerate(chunks):
        content = _sanitize_text(c.get("content") or "")
        filename = _sanitize_text(c.get("filename") or "Document")
        score = c.get("score")
        part = f"[{i + 1}] ({filename}" + (f", score: {score:.2f}" if score is not None else "") + ")\n" + content
        if total_len + len(part) > max_context:
            break
        context_parts.append(part)
        total_len += len(part)

    context = "\n\n---\n\n".join(context_parts)

    system_prompt = """You are an RFP assistant. Answer the user's question using ONLY the provided document passages. Be concise and accurate. If the passages do not contain enough information to answer, say so. Do not invent facts. Cite which passage(s) support your answer when relevant (e.g. "According to [1]...")."""

    question_clean = _sanitize_text(question)
    user_content = f"""Relevant passages from the knowledge base:\n\n{context}\n\nQuestion: {question_clean}\n\nAnswer (based only on the passages above):"""

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.openai_chat_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content[:_MAX_USER_CONTENT_CHARS]},
        ],
        "max_tokens": 1024,
    }

    with httpx.Client(timeout=60.0) as client:
        r = client.post(url, json=body, headers=headers)

    if r.status_code >= 400:
        err_preview = (r.text or "")[:1500]
        logger.error("GPT gateway returned %s: %s", r.status_code, err_preview)
        raise RuntimeError(f"GPT gateway returned {r.status_code}: {err_preview}")
    r.raise_for_status()

    data = r.json()
    choice = (data.get("choices") or [None])[0]
    message = (choice.get("message") or {}).get("content") if choice else ""
    answer = (message or "").strip()
    return answer or "I couldn't generate an answer from the retrieved passages.", None