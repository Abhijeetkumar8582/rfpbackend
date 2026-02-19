"""Generate a natural-language answer from search results using GPT (RAG)."""
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def _get_client():
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for GPT search answer.")
    from openai import OpenAI

    if settings.openai_base_url:
        return OpenAI(
            api_key=settings.openai_api_key, base_url=settings.openai_base_url
        ), settings.openai_chat_model
    return OpenAI(api_key=settings.openai_api_key), settings.openai_chat_model


def answer_from_chunks(question: str, chunks: list[dict]) -> str:
    """
    Use GPT to synthesize a concise answer from the given question and retrieved chunks.
    chunks: list of {content, filename, score} (or at least content).
    """
    if not chunks:
        return "No relevant passages were found. Try rephrasing your question or adding more documents to this project."

    client, model = _get_client()

    context_parts = []
    total_len = 0
    max_context = 6000
    for i, c in enumerate(chunks):
        content = c.get("content") or ""
        filename = c.get("filename") or "Document"
        score = c.get("score")
        part = f"[{i + 1}] ({filename}" + (f", score: {score:.2f}" if score is not None else "") + ")\n" + content
        if total_len + len(part) > max_context:
            break
        context_parts.append(part)
        total_len += len(part)

    context = "\n\n---\n\n".join(context_parts)

    system_prompt = """You are an RFP assistant. Answer the user's question using ONLY the provided document passages. Be concise and accurate. If the passages do not contain enough information to answer, say so. Do not invent facts. Cite which passage(s) support your answer when relevant (e.g. "According to [1]...")."""

    user_content = f"""Relevant passages from the knowledge base:\n\n{context}\n\nQuestion: {question}\n\nAnswer (based only on the passages above):"""

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content[:12_000]},
        ],
        max_tokens=1024,
    )
    answer = (resp.choices[0].message.content or "").strip()
    return answer or "I couldn't generate an answer from the retrieved passages."
