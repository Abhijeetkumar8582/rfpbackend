"""Rephrase an answer in a more technical way using GPT, given a question and original answer."""
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def _get_client():
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for rephrase.")
    from openai import OpenAI

    if settings.openai_base_url:
        return OpenAI(
            api_key=settings.openai_api_key, base_url=settings.openai_base_url
        ), settings.openai_chat_model
    return OpenAI(api_key=settings.openai_api_key), settings.openai_chat_model


def rephrase_answer(question: str, answer: str) -> str:
    """
    Use GPT to rephrase the given answer in a more technical way, in context of the question.
    Preserves meaning and accuracy while using precise terminology and structure.
    """
    client, model = _get_client()

    system_prompt = """You are an expert technical writer. Given a question and an answer, rephrase the answer in a more technical way. Use precise terminology, avoid casual language, and structure the response clearly. Do not add new facts or change the meaning—only make the wording more technical and professional. Keep the rephrased answer concise and to the point."""

    user_content = f"""Question:\n{question}\n\nOriginal answer:\n{answer}\n\nRephrase the answer above in a more technical way. Output only the rephrased answer, no preamble."""

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content[:8_000]},
        ],
        max_tokens=1024,
    )
    rephrased = (resp.choices[0].message.content or "").strip()
    return rephrased or answer
