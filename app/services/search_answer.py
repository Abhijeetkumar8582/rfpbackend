"""Generate a natural-language answer from search results using GPT (RAG).

Uses OPENAI_BASE_URL and OPENAI_API_KEY from .env (e.g. Druid gateway URL and token).

NOTE: This service does NOT use embeddings. Do not convert the question into an embedding
here — search is performed upstream (e.g. in search API) and this module receives
pre-retrieved chunks directly. The question is passed as plain text to GPT for synthesis.
"""
from __future__ import annotations

import json
import logging
import re

from app.services.openai_client import get_chat_client

logger = logging.getLogger(__name__)

# When no articles/chunks are found, answer text starts with this prefix (frontend uses it for unanswered count).
UNANSWERED_PREFIX = "Unanswered : "

# Max chars for the user message sent to GPT (some gateways 400 on very large payloads)
_MAX_USER_CONTENT_CHARS = 8000


def _strip_unanswered_prefix_variants(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return ""
    m = re.match(r"(?i)^unanswered\s*:\s*", t)
    if m:
        return t[m.end() :].lstrip()
    return t


def _looks_like_unanswered(body: str) -> bool:
    """Detect abstention answers when the model omits the explicit JSON flag."""
    t = (body or "").strip().lower()
    if not t:
        return True
    lead = (
        "the passages do not",
        "the documents do not",
        "the provided passages do not",
        "passages do not contain",
        "no relevant information",
        "there is no information",
        "there is not enough information",
        "the information is not available in",
        "none of the passages",
    )
    if any(t.startswith(p) for p in lead):
        return True
    snippets = (
        "passages do not specify",
        "do not specify any information",
        "not enough information in the passages",
        "cannot be determined from the provided",
    )
    if any(x in t for x in snippets):
        return True
    if t.startswith("i couldn't generate an answer") or t.startswith("i could not generate an answer"):
        return True
    return False


def ensure_unanswered_prefix(answer: str, *, unanswered: bool | None = None) -> str:
    """
    Prefix abstention / no-evidence answers with UNANSWERED_PREFIX (aligned with frontend and RFP metrics).

    If the model returns JSON with \"unanswered\": true, always prefix. If that field is absent, use a
    light heuristic for common abstention phrasing. If \"unanswered\": false, never prefix.
    """
    s = (answer or "").strip()
    if not s:
        return UNANSWERED_PREFIX + "No answer could be generated."
    body = _strip_unanswered_prefix_variants(s)
    if not body.strip():
        return UNANSWERED_PREFIX + "No answer could be generated."
    should = unanswered is True or (unanswered is not False and _looks_like_unanswered(body))
    if should:
        return UNANSWERED_PREFIX + body
    return s


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


def answer_from_chunks(
    question: str,
    chunks: list[dict],
    conversation_history: list[dict] | None = None,
) -> tuple[str, list[str], dict]:
    """
    Use GPT to synthesize a concise answer from the given question and retrieved chunks.
    chunks: list of {content, filename, score} (or at least content).
    Returns (answer, topics_covered, confidence).
    confidence: dict with keys overall, evidence_coverage, contradiction_risk (0-1 floats).
    Use confidence["overall"] as the single per-question value for RFP confidence array storage.

    Uses OPENAI_BASE_URL and OPENAI_API_KEY from .env for the chat completions request.
    """
    empty_topics: list[str] = []
    empty_confidence: dict = {"overall": 0.0, "evidence_coverage": 0.0, "contradiction_risk": 0.0}
    if not chunks:
        gpt_message = (
            "No relevant passages were found. Try rephrasing your question or adding more documents to this project."
        )
        return (
            UNANSWERED_PREFIX + gpt_message,
            empty_topics,
            empty_confidence,
        )

    client, model = get_chat_client()

    context_parts = []
    total_len = 0
    max_context = 9000  # More context for accurate synthesis
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

    system_prompt = """You are an RFP assistant. Answer the user's question using ONLY the provided document passages. Be accurate and well-supported. If the passages do not contain enough information to answer the question, say so clearly. Do not invent facts.

Rules for a strong answer:
1. **Cite evidence** — Use [1], [2], etc. when making claims (e.g. "According to [1], the SLA guarantees...").
2. **Be precise** — Include specific numbers, clauses, or conditions when present in the passages.
3. **Cover key points** — Don't skip relevant details; address the full question.
4. **Prioritize accuracy** — Prefer saying the passages do not specify over guessing.

You must respond with valid JSON only, no other text. Use this exact structure:
{"answer": "your answer here", "unanswered": false, "topics_covered": ["Topic1", "Topic2", ...], "confidence": {"overall": 0.81, "evidence_coverage": 0.76, "contradiction_risk": 0.12}}

- unanswered: required boolean. Set true if the passages do NOT contain enough information to answer the question (or only partially address it). Set false if the passages support a solid answer. Do NOT prepend the text "Unanswered" to the answer field — the API adds a standard prefix when unanswered is true.
- topics_covered: RFP topics (Payment terms, SLA, Security, Pricing, Delivery, Warranty, Liability, etc.). Use [] if none.
- confidence: 0-1 floats. overall = confidence; evidence_coverage = how well passages support it; contradiction_risk = risk of contradictions. Use low overall/evidence_coverage when unanswered is true."""

    history_parts: list[str] = []
    for i, h in enumerate(conversation_history or [], 1):
        q = _sanitize_text((h or {}).get("query") or "")
        a = _sanitize_text((h or {}).get("answer") or "")
        if not q and not a:
            continue
        history_parts.append(
            f"Turn {i}:\nUser: {q[:300]}\nAssistant: {a[:500]}"
        )
    history_text = "\n\n".join(history_parts)

    question_clean = _sanitize_text(question)
    if history_text:
        user_content = (
            f"""Recent conversation context:\n\n{history_text}\n\nRelevant passages from the knowledge base:\n\n{context}\n\nQuestion: {question_clean}\n\nUse the conversation context to resolve follow-up references (like "it", "that", "how many are vested"). Produce an accurate, well-cited answer. Respond with JSON only."""
        )
    else:
        user_content = (
            f"""Relevant passages from the knowledge base:\n\n{context}\n\nQuestion: {question_clean}\n\nProduce an accurate, well-cited answer. Respond with JSON only."""
        )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content[:_MAX_USER_CONTENT_CHARS]},
            ],
            max_tokens=8000,
            timeout=60.0,
        )
    except Exception as e:
        logger.error("GPT request failed: %s", e)
        raise

    raw_content = ((resp.choices[0].message.content or "") if resp and resp.choices else "").strip()

    # Parse JSON response: {"answer": "...", "unanswered": bool, "topics_covered": [...], "confidence": {...}}
    answer = "I couldn't generate an answer from the retrieved passages."
    topics_covered: list[str] = []
    confidence: dict = {"overall": 0.0, "evidence_coverage": 0.0, "contradiction_risk": 0.0}
    unanswered_flag: bool | None = None
    if raw_content:
        try:
            text = raw_content
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
            if match:
                text = match.group(1).strip()
            parsed = json.loads(text)
            answer = (parsed.get("answer") or "").strip() or answer
            if "unanswered" in parsed:
                unanswered_flag = bool(parsed.get("unanswered"))
            raw_topics = parsed.get("topics_covered")
            if isinstance(raw_topics, list):
                topics_covered = [str(t).strip() for t in raw_topics if t]
            elif isinstance(raw_topics, str) and raw_topics:
                topics_covered = [raw_topics.strip()]
            raw_conf = parsed.get("confidence")
            if isinstance(raw_conf, dict):
                confidence = {
                    "overall": float(raw_conf.get("overall", 0) or 0),
                    "evidence_coverage": float(raw_conf.get("evidence_coverage", 0) or 0),
                    "contradiction_risk": float(raw_conf.get("contradiction_risk", 0) or 0),
                }
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("GPT response was not valid JSON, using raw content as answer: %s", e)
            answer = raw_content

    answer = ensure_unanswered_prefix(answer, unanswered=unanswered_flag)
    return answer, topics_covered, confidence