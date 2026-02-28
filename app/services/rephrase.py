"""Rephrase an answer in a more technical way using GPT, given a question and original answer."""
from __future__ import annotations

import logging

from app.services.openai_client import get_chat_client

logger = logging.getLogger(__name__)


def rephrase_answer(question: str, answer: str) -> str:
    """
    Use GPT to rephrase the given answer in a more technical way, in context of the question.
    Preserves meaning and accuracy while using precise terminology and structure.
    """
    client, model = get_chat_client()

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
