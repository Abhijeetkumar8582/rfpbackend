"""Agentic reasoning pipeline for search: query understanding, rewriting, evidence bundling, reranking, self-check.

Phases 1-3:
- Layer 1: Query understanding (intent, domain, answer type, constraints)
- Layer 2: Query rewriting (3-6 search variants)
- Layer 3: Evidence bundling (group by doc, sort by chunk_index)
- Layer 4: Reranking (cross-encoder)
- Layer 5: Self-check (validate answer, detect gaps)
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.config import settings
from app.services.openai_client import get_chat_client

logger = logging.getLogger(__name__)

_MAX_USER_CONTENT_CHARS = 8000


def _sanitize_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\x00", " ")
    try:
        return s.encode("utf-8", errors="replace").decode("utf-8")
    except Exception:
        return ""


def _gpt_json(messages: list[dict], max_tokens: int = 2048) -> dict:
    """Call GPT and parse JSON response. Returns dict or empty dict on failure."""
    client, model = get_chat_client()
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        timeout=90.0,
    )
    content = ((resp.choices[0].message.content or "") if resp and resp.choices else "").strip()

    if not content:
        return {}

    text = content
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def validate_faq_answers(
    items: list[tuple[int, str, str]],
) -> list[dict]:
    """
    For each (search_query_id, question, answer), ask LLM to rate 0-100 how well
    the answer addresses the question. Returns list of { search_query_id, confidence }.
    """
    if not items:
        return []
    client, model = get_chat_client()

    parts = []
    for i, (sid, q, a) in enumerate(items, 1):
        q_short = (_sanitize_text(q) or "N/A")[:500]
        a_short = (_sanitize_text(a) or "N/A")[:500]
        parts.append(f"Pair {i}:\nQuestion: {q_short}\nAnswer: {a_short}")
    prompt = """You are a validator. For each pair below, rate how well the Answer addresses the Question (relevance and correctness). Reply with a JSON object with a single key "scores" whose value is an array of integers from 0 to 100, one per pair, in the same order. Only output valid JSON, no other text.

"""
    prompt += "\n\n".join(parts)
    prompt += "\n\nOutput format: {\"scores\": [n1, n2, ...]}"

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You output only valid JSON. No markdown, no explanation."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=512,
        timeout=60.0,
    )
    content = ((resp.choices[0].message.content or "") if resp and resp.choices else "")
    text = (content or "").strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        text = match.group(1).strip()
    scores = []
    try:
        parsed = json.loads(text)
        scores = parsed.get("scores") or parsed.get("Scores") or []
    except json.JSONDecodeError:
        arr = re.search(r"\[\s*\d+\s*(?:,\s*\d+\s*)*\]", text)
        if arr:
            try:
                scores = json.loads(arr.group(0))
            except json.JSONDecodeError:
                pass

    ids = [x[0] for x in items]
    while len(scores) < len(ids):
        scores.append(0)
    results = []
    for i, sid in enumerate(ids):
        sc = scores[i] if i < len(scores) else 0
        if not isinstance(sc, (int, float)):
            try:
                sc = int(float(str(sc)))
            except (ValueError, TypeError):
                sc = 0
        sc = max(0, min(100, int(sc)))
        results.append({"search_query_id": sid, "confidence": sc})
    return results


# ---------------------------------------------------------------------------
# Layer 1 + 2: Query understanding and rewriting (single LLM call)
# ---------------------------------------------------------------------------


def analyze_and_rewrite_query(question: str) -> tuple[dict, list[str]]:
    """
    Analyze the question (intent, domain, answer type, constraints) and generate
    3-6 search query variants for better retrieval.
    Returns (query_analysis, search_queries).
    """
    system = """You are a search query analyst for an RFP/policy document system.

Analyze the user's question and produce:
1. query_analysis: structured understanding
2. search_queries: 3-6 alternative search strings that are logical, specific, and detailed to improve retrieval

Respond with valid JSON only. Use this exact structure:
{
  "query_analysis": {
    "intent": "policy lookup|comparison|definition|calculation|exception|general",
    "domain": "HR|legal|security|pricing|technical|general",
    "answer_type": "short fact|list|step-by-step|clause-based|comparison",
    "constraints": {"geography": null, "employee_type": null, "version": null, "date": null},
    "missing_constraints": ["list any missing info that would help narrow the search"]
  },
  "search_queries": [
    "original or slightly cleaned query",
    "expanded/semantic query with key concepts",
    "detailed keyword-heavy query with important terms",
    "policy/clause-style phrasing",
    "alternative formulation"
  ]
}

- query_analysis: Be precise. For missing_constraints, list concrete details that would narrow the search (e.g. region, employee type, effective date).
- search_queries: 3-6 strings. Each query must be:
  * Logical: clearly express one coherent intent; avoid vague or fragmented phrasing.
  * Detailed: include key concepts, criteria, or scope (e.g. "SLA uptime guarantees and penalties for enterprise contracts" not just "SLA").
  * Specific: name policy areas, document types, or conditions when relevant (e.g. "remote work policy for full-time employees" not just "remote work").
  Include the original question as the first element. Make others diverse: full semantic phrasing, keyword-rich detailed query, formal/policy language, and one that spells out assumptions or context.
  Keep each query under 200 characters so they remain detailed but usable for search.
"""

    user = f"Question: {_sanitize_text(question)[:500]}"

    try:
        out = _gpt_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=1024,
        )
    except Exception as e:
        logger.warning("Query analysis failed: %s", e)
        return {}, [question]

    analysis = out.get("query_analysis") or {}
    queries = out.get("search_queries") or []
    if not isinstance(analysis, dict):
        analysis = {}
    if not isinstance(queries, list):
        queries = [question]

    # Ensure we have at least the original
    clean_q = (question or "").strip()[:200]
    if clean_q and clean_q not in queries:
        queries = [clean_q] + [q for q in queries if q][:5]
    elif not queries:
        queries = [clean_q or "general policy"]

    return analysis, queries[:6]


# ---------------------------------------------------------------------------
# Layer 3: Evidence bundling
# ---------------------------------------------------------------------------


def bundle_evidence(chunks: list[dict]) -> list[dict]:
    """
    Group chunks by document, sort by chunk_index within each doc.
    Chunks are dicts with: content, filename, score, document_id, chunk_index.
    Returns flattened list in bundled order (doc groups, sorted by chunk_index).
    """
    if not chunks:
        return []

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for c in chunks:
        doc_id = str(c.get("document_id", ""))
        by_doc[doc_id].append(c)

    bundled: list[dict] = []
    for doc_id in sorted(by_doc.keys()):
        doc_chunks = by_doc[doc_id]
        doc_chunks.sort(key=lambda x: int(x.get("chunk_index", 0)))
        bundled.extend(doc_chunks)

    return bundled


# ---------------------------------------------------------------------------
# Layer 4: Reranking (cross-encoder)
# ---------------------------------------------------------------------------

_rerank_model = None


def _get_rerank_model():
    global _rerank_model
    if _rerank_model is None:
        try:
            from sentence_transformers import CrossEncoder
            _rerank_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        except ImportError:
            logger.warning("sentence-transformers not installed; reranking disabled")
            return None
    return _rerank_model


def rerank_chunks(question: str, chunks: list[dict], top_k: int = 12) -> list[dict]:
    """
    Rerank chunks using a cross-encoder. Returns top_k chunks by relevance.
    If sentence-transformers not available, returns chunks unchanged.
    """
    model = _get_rerank_model()
    if not model or not chunks:
        return chunks[:top_k]

    pairs = [(question, (c.get("content") or "")[:2000]) for c in chunks]
    try:
        scores = model.predict(pairs)
    except Exception as e:
        logger.warning("Rerank failed: %s", e)
        return chunks[:top_k]

    if isinstance(scores, (int, float)):
        scores = [scores]
    scored = list(zip(chunks, scores))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in scored[:top_k]]


# ---------------------------------------------------------------------------
# Answer synthesis (enhanced with uncertainty + missing info)
# ---------------------------------------------------------------------------


def reasoning_answer_from_chunks(
    question: str,
    chunks: list[dict],
    query_analysis: dict | None = None,
) -> tuple[str, list[str], dict, str | None, str | None]:
    """
    Synthesize answer with citations, uncertainty note, and missing info note.
    Returns (answer, topics_covered, confidence, uncertainty_note, missing_info_note).
    """
    client, model = get_chat_client()

    empty_topics: list[str] = []
    empty_conf = {"overall": 0.0, "evidence_coverage": 0.0, "contradiction_risk": 0.0}

    if not chunks:
        return (
            "No relevant passages were found. Try rephrasing your question or adding more documents.",
            empty_topics,
            empty_conf,
            "No evidence found.",
            "Consider rephrasing or adding relevant documents.",
        )

    context_parts = []
    total_len = 0
    max_context = 8000  # More evidence for detailed reasoning answers
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

    system = """You are an expert RFP assistant producing detailed, well-reasoned answers. Use ONLY the provided document passages. Do not invent facts. Produce a STRONG, DETAILED answer that:

1. **Direct answer first** — Start with a clear, direct response to the question.
2. **Supporting reasoning** — Explain the key evidence and logic that support your answer.
3. **Key points** — List or elaborate important details, clauses, numbers, or conditions from the documents.
4. **Citations** — Explicitly cite passages using [1], [2], etc. when making claims (e.g. "According to [1], the SLA guarantees 99.9% uptime...").
5. **Context** — Where relevant, include document names, section references, or policy context.
6. **Breadth** — Cover all relevant aspects from the evidence; do not skip important details.

Be thorough rather than terse. If the passages are insufficient, say so and explain what is missing. Structure longer answers with clear paragraphs or bullet points for readability.

Respond with valid JSON only. Use this exact structure:
{
  "answer": "your detailed, well-reasoned answer here (can be multiple paragraphs)",
  "topics_covered": ["Topic1", "Topic2"],
  "confidence": {"overall": 0.81, "evidence_coverage": 0.76, "contradiction_risk": 0.12},
  "uncertainty_note": "Optional: any caveats or limitations",
  "missing_info_note": "Optional: what information is missing from the passages"
}

- answer: A strong, comprehensive answer. Not one sentence — include reasoning, evidence, and key details.
- topics_covered: RFP topics (Payment terms, SLA, Security, Pricing, etc.). Use [] if none.
- confidence: 0-1 floats.
- uncertainty_note: null or string if answer has caveats.
- missing_info_note: null or string if key info is missing from passages."""

    analysis_hint = ""
    if query_analysis:
        intent = query_analysis.get("intent", "")
        domain = query_analysis.get("domain", "")
        if intent or domain:
            analysis_hint = f"\nQuery context: intent={intent}, domain={domain}\n"

    user_content = f"""Relevant passages:\n\n{context}\n\nQuestion: {_sanitize_text(question)}{analysis_hint}\n\nProduce a detailed, well-reasoned answer. Respond with JSON only."""
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content[:_MAX_USER_CONTENT_CHARS]},
        ],
        max_tokens=8000,
        timeout=90.0,
    )
    raw = ((resp.choices[0].message.content or "") if resp and resp.choices else "")

    answer = "I couldn't generate an answer from the retrieved passages."
    topics_covered = empty_topics
    confidence = empty_conf.copy()
    uncertainty_note: str | None = None
    missing_info_note: str | None = None

    if raw:
        try:
            text = raw.strip()
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
            if m:
                text = m.group(1).strip()
            parsed = json.loads(text)
            answer = (parsed.get("answer") or "").strip() or answer
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
            uncertainty_note = parsed.get("uncertainty_note")
            missing_info_note = parsed.get("missing_info_note")
            if isinstance(uncertainty_note, str) and not uncertainty_note.strip():
                uncertainty_note = None
            if isinstance(missing_info_note, str) and not missing_info_note.strip():
                missing_info_note = None
        except (json.JSONDecodeError, TypeError):
            answer = raw

    return answer, topics_covered, confidence, uncertainty_note, missing_info_note


# ---------------------------------------------------------------------------
# Layer 5: Self-check
# ---------------------------------------------------------------------------


def self_check(
    question: str,
    answer: str,
    chunks: list[dict],
) -> tuple[bool, list[str], bool]:
    """
    Validate the answer. Returns (passed, issues, clarification_suggested).
    """
    if not answer:
        return False, ["No answer produced"], True

    url = (settings.openai_base_url or "").strip()
    token = (settings.openai_api_key or "").strip()
    if not url or not token:
        return True, [], False

    evidence_preview = "\n".join(
        (c.get("content") or "")[:300] for c in chunks[:5]
    )[:1500]

    system = """You are a quality validator for RAG answers. Check if the answer:
1. Actually addresses the question
2. Has enough evidence in the passages
3. Has contradictions
4. Is too broad or vague
5. Should ask the user for clarification (e.g. ambiguous question)

Respond with valid JSON only:
{
  "passed": true,
  "issues": ["list of issues if any"],
  "clarification_suggested": false
}

- passed: true if answer is acceptable; false if significant problems.
- issues: empty array or list of specific problems.
- clarification_suggested: true if the system should ask the user to clarify."""

    user = f"""Question: {_sanitize_text(question)[:300]}\n\nAnswer: {_sanitize_text(answer)[:1000]}\n\nEvidence preview:\n{evidence_preview[:800]}"""

    try:
        out = _gpt_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=512,
        )
    except Exception as e:
        logger.warning("Self-check failed: %s", e)
        return True, [], False

    passed = bool(out.get("passed", True))
    issues = out.get("issues") or []
    if not isinstance(issues, list):
        issues = []
    clarification_suggested = bool(out.get("clarification_suggested", False))

    return passed, issues, clarification_suggested


# ---------------------------------------------------------------------------
# Save reasoning search to DB (search_queries table)
# ---------------------------------------------------------------------------


def save_reasoning_search(
    db: "Session",
    *,
    actor_user_id: str | None,
    conversation_id: str,
    query_text: str,
    k: int,
    results_count: int,
    latency_ms: int | None,
    answer: str | None = None,
    topic: str | None = None,
    sources_json: list | None = None,
    confidence_json: dict | None = None,
    sources_document_metadata_json: list | None = None,
    answer_status: str | None = None,
    no_answer_reason: str | None = None,
):
    """Persist a reasoning search to the search_queries table. Returns the created SearchQuery row."""
    from app.models.search_query import SearchQuery

    row = SearchQuery(
        datetime_=datetime.now(timezone.utc),
        conversation_id=conversation_id,
        actor_user_id=actor_user_id,
        query_text=query_text,
        k=k,
        filters_json=None,
        results_count=results_count,
        latency_ms=latency_ms,
        answer=answer,
        topic=topic,
        sources_json=sources_json,
        confidence_json=confidence_json,
        sources_document_metadata_json=sources_document_metadata_json,
        answer_status=answer_status,
        no_answer_reason=no_answer_reason,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
