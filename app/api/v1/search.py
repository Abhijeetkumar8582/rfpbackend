"""Search API — semantic search via Qdrant (question embedding vs stored chunk embeddings)."""
import json
import logging
import os
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func

from app.api.deps import DbSession, CurrentUser, CurrentUserOptional, require_admin_only
from app.models.search_query import SearchQuery
from app.models.document import Document, DocumentStatus
from app.models.project import Project
from app.schemas.search import (
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    SearchQueryResponse,
    SearchFeedbackRequest,
    SearchAnswerResponse,
    SearchChatRequest,
    SearchChatResponse,
    SourceItem,
    ConfidenceScores,
    ReasoningRequest,
    ReasoningResponse,
    QueryAnalysis,
    SearchBalance,
    IntelligenceHubResponse,
    IntelligenceHubTopic,
    IntelligenceHubLowConfidence,
    IntelligenceHubHighConfidence,
    IntelligenceHubGap,
    IntelligenceHubRecentDoc,
    IndexHealth,
)
from app.services.embeddings import get_embedding
from app.services.qdrant import query_collection, query_collection_multi, get_collection_count
from app.services.search_answer import answer_from_chunks
from app.services.query_intelligence import run_query_intelligence
from app.services.reasoning import (
    analyze_and_rewrite_query,
    apply_search_balance_fusion,
    bundle_evidence,
    rerank_chunks,
    reasoning_answer_from_chunks,
    save_reasoning_search,
    self_check,
)
from app.utils.conversation_id import generate_conversation_id, is_conversation_valid
from app.services.activity_log import log_activity
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])
_MIN_CONFIDENCE_FOR_GPT = 0.50
_QUERY_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in",
    "is", "it", "many", "much", "of", "on", "or", "that", "the", "to", "what",
    "when", "where", "which", "who", "why", "with", "your", "you", "my", "our",
    "their", "this", "these", "those",
}


def _embedding_failure_detail(exc: BaseException) -> str:
    err_msg = str(exc).strip() or type(exc).__name__
    if "401" in err_msg or "invalid issuer" in err_msg.lower() or "authentication" in err_msg.lower():
        return (
            "Embedding service auth failed. If using a gateway (e.g. Druid), set OPENAI_BASE_URL "
            "and ensure the token is valid for that gateway."
        )
    return f"Embedding failed: {err_msg}"


def _qdrant_failure_detail(exc: BaseException) -> str:
    err_msg = str(exc).strip() or type(exc).__name__
    low = err_msg.lower()
    hint = (
        " Set QDRANT_LOCAL_PATH in .env for on-disk Qdrant (no server), or run Qdrant and match QDRANT_URL."
    )
    if "already accessed by another instance" in low or "alreadylocked" in low:
        return (
            f"Vector store lock conflict: {err_msg}. "
            "Only one process can use embedded Qdrant path at a time. "
            "Use a shared Qdrant server (QDRANT_URL) or run a single backend process."
        )
    if "10061" in err_msg or "connection refused" in low or "actively refused" in low:
        return f"Vector store (Qdrant) unreachable: {err_msg}.{hint}"
    return f"Vector store (Qdrant) failed: {err_msg}"


def _compute_answer_status_and_reason(
    *,
    results_count: int,
    confidence_json: dict | None,
    sources_json: list | None,
    clarification_suggested: bool = False,
    self_check_passed: bool = True,
    self_check_issues: list[str] | None = None,
    missing_info_note: str | None = None,
) -> tuple[str, str | None]:
    """
    Compute answer_status and no_answer_reason for gap analysis.
    Returns (answer_status, no_answer_reason). no_answer_reason is None when answer_status is 'answered'.
    """
    conf = confidence_json or {}
    overall = conf.get("overall")
    if overall is not None and not isinstance(overall, (int, float)):
        overall = 0.0
    overall = float(overall) if overall is not None else 0.0
    retrieval_avg_top3 = float(conf.get("retrieval_avg_top3") or 0)
    evidence_coverage = float(conf.get("evidence_coverage") or 0)
    contradiction_risk = float(conf.get("contradiction_risk") or 0)

    has_usable_sources = bool(sources_json and len(sources_json) > 0)

    # Determine answer_status (order matters)
    if results_count == 0 or not has_usable_sources or overall == 0:
        status = "unanswered"
    elif clarification_suggested:
        status = "needs_clarification"
    elif contradiction_risk >= 0.5:
        status = "contradictory"
    elif not self_check_passed and self_check_issues:
        issues_text = " ".join(self_check_issues).lower()
        if any(kw in issues_text for kw in ("out of scope", "unsupported", "not covered", "cannot answer")):
            status = "unsupported"
        else:
            status = "low_confidence"
    elif overall < 0.5:
        status = "low_confidence"
    elif overall < 0.75:
        status = "low_confidence"
    else:
        status = "answered"

    # Determine no_answer_reason (only when not answered)
    reason: str | None = None
    if status != "answered":
        if results_count == 0:
            reason = "no_results"
        elif retrieval_avg_top3 < 0.3:
            reason = "low_retrieval_score"
        elif evidence_coverage < 0.4:
            reason = "insufficient_evidence"
        elif contradiction_risk >= 0.5:
            reason = "conflicting_sources"
        elif clarification_suggested:
            reason = "needs_user_clarification"
        elif missing_info_note and any(
            kw in (missing_info_note or "").lower()
            for kw in ("topic", "missing", "not covered", "no information", "gap")
        ):
            reason = "missing_topic"
        elif retrieval_avg_top3 < 0.5:
            reason = "low_retrieval_score"
        elif evidence_coverage < 0.6:
            reason = "insufficient_evidence"

    return status, reason


def _build_sources_document_metadata(
    db: DbSession,
    project_id: str,
    document_ids: list[str],
) -> list[dict]:
    """
    Fetch document metadata for each document_id. Returns a list of metadata dicts
    (one per unique document) for gap analysis: outdated knowledge, folder coverage,
    missing categories, multilingual support.
    """
    if not document_ids:
        return []
    seen: set[str] = set()
    unique_ids: list[str] = []
    for x in document_ids:
        if x and x not in seen:
            seen.add(x)
            unique_ids.append(x)
    rows = db.execute(
        select(Document).where(
            Document.project_id == project_id,
            Document.id.in_(unique_ids),
        )
    ).scalars().all()
    docs = {r.id: r for r in rows}
    result: list[dict] = []
    for doc_id in unique_ids:
        doc = docs.get(doc_id)
        if not doc:
            result.append({"document_id": doc_id, "title": None, "doc_type": None, "domain": None, "folder_id": None, "folder_path": None, "uploaded_at": None, "updated_at": None, "status": None, "language": None, "tags": None})
            continue
        title = doc.doc_title or (doc.filename.rsplit(".", 1)[0] if doc.filename else doc.filename)
        folder_path = os.path.dirname(doc.storage_path) if doc.storage_path else None
        updated_at = doc.ingested_at or doc.uploaded_at
        tags = None
        if doc.tags_json:
            try:
                tags = json.loads(doc.tags_json) if isinstance(doc.tags_json, str) else doc.tags_json
            except (json.JSONDecodeError, TypeError):
                pass
        result.append({
            "document_id": doc.id,
            "title": title,
            "doc_type": doc.doc_type,
            "domain": doc.cluster,
            "folder_id": doc.project_id,
            "folder_path": folder_path,
            "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
            "updated_at": updated_at.isoformat() if updated_at else None,
            "status": doc.status.value if doc.status else None,
            "language": None,
            "tags": tags,
        })
    return result


def _save_search_query(
    db: DbSession,
    *,
    actor_user_id: str | None,
    conversation_id: str,
    query_text: str,
    k: int,
    results_count: int,
    latency_ms: int | None,
    filters_json: dict | None = None,
    answer: str | None = None,
    topic: str | None = None,
    sources_json: list | None = None,
    confidence_json: dict | None = None,
    sources_document_metadata_json: list | None = None,
    answer_status: str | None = None,
    no_answer_reason: str | None = None,
) -> SearchQuery | None:
    """Persist one search to search_queries table. Returns the created row or None on failure."""
    row = SearchQuery(
        datetime_=datetime.now(timezone.utc),
        conversation_id=conversation_id,
        actor_user_id=actor_user_id,
        query_text=query_text,
        k=k,
        filters_json=filters_json,
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


def _resolve_conversation_id(db: DbSession, conversation_id_from_body: str | None) -> str:
    """Return a valid conversation_id: reuse body's if new thread or still within 24h, else generate new."""
    if not conversation_id_from_body or len(conversation_id_from_body) < 10:
        return generate_conversation_id()
    from sqlalchemy import func
    result = db.execute(
        select(func.min(SearchQuery.datetime_)).where(SearchQuery.conversation_id == conversation_id_from_body)
    )
    first_ts = result.scalar()
    if first_ts is None:
        # First query in this conversation — keep client-supplied id (e.g. RFP Excel bulk, new chat).
        return conversation_id_from_body
    if is_conversation_valid(first_ts):
        return conversation_id_from_body
    return generate_conversation_id()


def _load_recent_conversation_history(
    db: DbSession,
    conversation_id: str,
    *,
    max_turns: int = 3,
) -> list[dict]:
    if not conversation_id:
        return []
    rows = db.execute(
        select(SearchQuery)
        .where(SearchQuery.conversation_id == conversation_id)
        .order_by(SearchQuery.datetime_.desc())
        .limit(max_turns)
    ).scalars().all()
    history: list[dict] = []
    for r in reversed(rows):
        q = (r.query_text or "").strip()
        a = (r.answer or "").strip()
        if q or a:
            history.append({"query": q, "answer": a})
    return history


def _is_followup_query(query_text: str) -> bool:
    q = (query_text or "").strip().lower()
    if not q:
        return False
    terms = q.split()
    if len(terms) <= 6:
        return True
    follow_markers = (
        "it", "that", "those", "these", "they", "them",
        "this", "same", "also", "and what", "how many are",
        "what about", "how about", "now",
    )
    return any(marker in q for marker in follow_markers)


def _build_contextual_query(query_text: str, history: list[dict]) -> str:
    """
    Make follow-up questions standalone for better retrieval.
    """
    if not history or not _is_followup_query(query_text):
        return query_text
    last = history[-1]
    last_q = (last.get("query") or "").strip()
    last_a = (last.get("answer") or "").strip()
    context = f"Previous question: {last_q[:220]}"
    if last_a:
        context += f". Previous answer summary: {last_a[:280]}"
    return f"{query_text}. Context: {context}"


def _split_compound_query(query_text: str, *, max_parts: int = 4) -> list[str]:
    """
    Split compound questions like "A and B", "A or B", "A & B" into sub-questions.
    """
    text = " ".join((query_text or "").strip().split())
    if not text:
        return []
    raw_parts = re.split(r"\s+(?:and|or|&)\s+", text, flags=re.IGNORECASE)
    if len(raw_parts) <= 1:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        p = part.strip(" \t\r\n,.;:")
        if len(p) < 4:
            continue
        low = p.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(p)
        if len(out) >= max_parts:
            break
    return out if len(out) >= 2 else []


def _merge_query_variants(primary: list[str], secondary: list[str], *, max_items: int = 6) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for q in list(primary) + list(secondary):
        s = (q or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        merged.append(s)
        if len(merged) >= max_items:
            break
    return merged


def _build_synthesis_question(query_text: str, sub_questions: list[str]) -> str:
    if not sub_questions:
        return query_text
    lines = "\n".join(f"{i+1}. {q}" for i, q in enumerate(sub_questions))
    return (
        f"{query_text}\n\nSub-questions to answer and merge:\n{lines}\n"
        "Return one combined answer that covers all sub-questions."
    )


def _compute_answer_status_and_reason(
    *,
    results_count: int,
    confidence_json: dict | None,
    sources_json: list | None,
    clarification_suggested: bool = False,
    self_check_passed: bool = True,
    self_check_issues: list[str] | None = None,
    missing_info_note: str | None = None,
) -> tuple[str, str | None]:
    """
    Compute answer_status and no_answer_reason for gap analysis.
    Returns (answer_status, no_answer_reason).
    no_answer_reason is set only when answer_status != "answered".
    """
    conf = confidence_json or {}
    overall = conf.get("overall")
    if overall is not None and not isinstance(overall, (int, float)):
        overall = 0.0
    overall = float(overall) if overall is not None else 0.0
    retrieval_avg_top3 = float(conf.get("retrieval_avg_top3") or 0)
    evidence_coverage = float(conf.get("evidence_coverage") or 0)
    contradiction_risk = float(conf.get("contradiction_risk") or 0)

    has_usable_sources = bool(sources_json and len(sources_json) > 0)
    issues = self_check_issues or []
    issue_text = " ".join(issues).lower() if issues else ""

    # --- Determine answer_status ---
    if results_count == 0 or not has_usable_sources or overall == 0:
        status = "unanswered"
    elif clarification_suggested:
        status = "needs_clarification"
    elif contradiction_risk > 0.5:
        status = "contradictory"
    elif not self_check_passed and (
        "out of scope" in issue_text or "unsupported" in issue_text or "cannot answer" in issue_text
    ):
        status = "unsupported"
    elif overall < 0.5:
        status = "low_confidence"
    else:
        status = "answered"

    # --- Determine no_answer_reason (only when not answered) ---
    reason: str | None = None
    if status != "answered":
        if results_count == 0:
            reason = "no_results"
        elif retrieval_avg_top3 < 0.3:
            reason = "low_retrieval_score"
        elif evidence_coverage < 0.4:
            reason = "insufficient_evidence"
        elif contradiction_risk > 0.5:
            reason = "conflicting_sources"
        elif clarification_suggested:
            reason = "needs_user_clarification"
        elif missing_info_note and (
            "topic" in missing_info_note.lower() or "not covered" in missing_info_note.lower()
        ):
            reason = "missing_topic"
        elif retrieval_avg_top3 < 0.5:
            reason = "low_retrieval_score"
        elif evidence_coverage < 0.6:
            reason = "insufficient_evidence"
        else:
            reason = "insufficient_evidence"  # fallback

    return status, reason


def _opt_positive_int(val: object) -> int | None:
    if val is None:
        return None
    try:
        n = int(val)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _document_source_open_url(doc: Document | None, page: int | None) -> str | None:
    """Public URL to open the stored file; skips local-only storage. Appends #page=N for PDF deep links."""
    if not doc or not doc.storage_path:
        return None
    if doc.storage_path.startswith("local/"):
        return None
    frag = f"#page={page}" if page and page > 0 else ""
    if getattr(doc, "s3_url", None):
        return f"{doc.s3_url}{frag}"
    base = settings.backend_public_url.rstrip("/")
    return f"{base}{settings.api_v1_prefix}/documents/{doc.id}/download{frag}"


def _enrich_results_source_urls(
    db: DbSession,
    project_id: str,
    results: list[SearchResultItem],
) -> list[SearchResultItem]:
    if not results:
        return results
    ids = list({r.document_id for r in results if r.document_id})
    if not ids:
        return results
    rows = db.execute(
        select(Document).where(
            Document.project_id == project_id,
            Document.id.in_(ids),
        )
    ).scalars().all()
    by_id = {d.id: d for d in rows}
    enriched: list[SearchResultItem] = []
    for r in results:
        doc = by_id.get(r.document_id)
        page = r.page_start if r.page_start and r.page_start > 0 else None
        url = _document_source_open_url(doc, page)
        enriched.append(r.model_copy(update={"source_url": url}))
    return enriched


def _build_sources(
    results: list[SearchResultItem],
    chroma_ids: list[str],
) -> list[SourceItem]:
    """Build source items from search results for the answer response."""
    sources: list[SourceItem] = []
    _SNIPPET_MAX = 150
    for i, r in enumerate(results):
        chunk_id = chroma_ids[i] if i < len(chroma_ids) else f"{r.document_id}:{r.chunk_index}"
        # Title: filename without extension, with spaces instead of hyphens
        base = (r.filename or "").rsplit(".", 1)[0] if r.filename else ""
        title = base.replace("-", " ").replace("_", " ") if base else r.filename or "Document"
        snippet = (r.content or "")[: _SNIPPET_MAX]
        if len(r.content or "") > _SNIPPET_MAX:
            snippet = snippet.rstrip() + "..."
        sources.append(
            SourceItem(
                document_id=r.document_id,
                title=title,
                filename=r.filename or "",
                chunk_id=chunk_id,
                page_start=r.page_start,
                page_end=r.page_end,
                section=r.section,
                snippet=snippet,
                score=round(r.score, 2),
                source_url=r.source_url,
            )
        )
    return sources


def _extract_query_terms(query_text: str) -> list[str]:
    parts = re.split(r"[^a-z0-9]+", (query_text or "").lower())
    terms: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if len(part) < 3 or part in _QUERY_STOPWORDS or part in seen:
            continue
        seen.add(part)
        terms.append(part)
    return terms


def _metadata_corpus_for_doc(doc: Document | None, fallback_filename: str) -> str:
    if not doc:
        return (fallback_filename or "").lower()
    chunks: list[str] = [
        doc.filename or "",
        doc.doc_title or "",
        doc.doc_description or "",
        doc.doc_type or "",
        doc.cluster or "",
    ]
    if doc.tags_json:
        try:
            parsed = json.loads(doc.tags_json) if isinstance(doc.tags_json, str) else doc.tags_json
            if isinstance(parsed, list):
                chunks.extend(str(x) for x in parsed if x)
            elif isinstance(parsed, dict):
                chunks.extend(str(x) for x in parsed.values() if x)
        except Exception:
            pass
    return " ".join(chunks).lower()


def _content_overlap_score(query_terms: list[str], content: str) -> float:
    if not query_terms:
        return 0.0
    body = (content or "").lower()
    if not body:
        return 0.0
    hits = sum(1 for term in query_terms if term in body)
    return min(1.0, hits / max(1, len(query_terms)))


def _filter_results_by_confidence(
    results: list[SearchResultItem],
    *,
    min_score_exclusive: float = _MIN_CONFIDENCE_FOR_GPT,
) -> list[SearchResultItem]:
    return [r for r in results if float(r.score or 0.0) > min_score_exclusive]


def _filter_chunk_dicts_by_confidence(
    chunk_dicts: list[dict],
    *,
    min_score_exclusive: float = _MIN_CONFIDENCE_FOR_GPT,
) -> list[dict]:
    return [c for c in chunk_dicts if float(c.get("score") or 0.0) > min_score_exclusive]


def _rerank_results_by_metadata(
    db: DbSession,
    project_id: str,
    query_text: str,
    results: list[SearchResultItem],
    chunk_dicts: list[dict] | None = None,
) -> tuple[list[SearchResultItem], list[dict] | None]:
    if not results:
        return results, chunk_dicts

    query_terms = _extract_query_terms(query_text)
    if not query_terms:
        return results, chunk_dicts

    doc_ids = list({r.document_id for r in results if r.document_id})
    if not doc_ids:
        return results, chunk_dicts

    docs = db.execute(
        select(Document).where(
            Document.project_id == project_id,
            Document.id.in_(doc_ids),
        )
    ).scalars().all()
    by_id = {d.id: d for d in docs}

    ranked_rows: list[tuple[float, float, float, int]] = []
    for idx, r in enumerate(results):
        metadata_text = _metadata_corpus_for_doc(by_id.get(r.document_id), r.filename)
        metadata_hits = sum(1 for term in query_terms if term in metadata_text)
        metadata_score = min(1.0, metadata_hits / max(1, len(query_terms)))
        lexical_score = _content_overlap_score(query_terms, r.content[:1200])
        vector_score = max(0.0, min(1.0, float(r.score or 0.0)))
        # Metadata is primary, lexical second, vector score as tie-breaker.
        combined = (0.70 * metadata_score) + (0.20 * lexical_score) + (0.10 * vector_score)
        ranked_rows.append((combined, metadata_score, vector_score, idx))

    ranked_rows.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    ordered_results = [results[idx] for _, _, _, idx in ranked_rows]
    for i, (combined, _, _, _) in enumerate(ranked_rows):
        ordered_results[i].score = round(combined, 4)

    ordered_chunks: list[dict] | None = None
    if chunk_dicts is not None and len(chunk_dicts) == len(results):
        ordered_chunks = [chunk_dicts[idx] for _, _, _, idx in ranked_rows]
        for i, (combined, _, _, _) in enumerate(ranked_rows):
            ordered_chunks[i]["score"] = round(combined, 4)

    return ordered_results, ordered_chunks


def _select_metadata_candidate_doc_ids(
    db: DbSession,
    project_id: str,
    query_text: str,
    *,
    limit: int = 6,
) -> list[str]:
    terms = _extract_query_terms(query_text)
    if not terms:
        return []
    docs = db.execute(
        select(Document).where(
            Document.project_id == project_id,
            Document.deleted_at.is_(None),
        )
    ).scalars().all()
    scored: list[tuple[float, str]] = []
    for d in docs:
        corpus = _metadata_corpus_for_doc(d, d.filename or "")
        if not corpus:
            continue
        hits = sum(1 for t in terms if t in corpus)
        if hits <= 0:
            continue
        score = hits / max(1, len(terms))
        scored.append((score, d.id))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [doc_id for _, doc_id in scored[:limit]]


def _run_qdrant_retrieval(
    *,
    project_id: str,
    queries: list[str],
    n_results: int,
    document_ids: list[str] | None = None,
    payload_filters: dict | None = None,
) -> dict:
    if len(queries) == 1:
        emb = get_embedding(queries[0])
        return query_collection(
            project_id=project_id,
            query_embedding=emb,
            n_results=n_results,
            document_ids=document_ids,
            query_text=queries[0],
            payload_filters=payload_filters,
        )
    query_embeddings = [get_embedding(q) for q in queries]
    return query_collection_multi(
        project_id=project_id,
        query_embeddings=query_embeddings,
        query_texts=queries,
        n_results_per_query=max(5, n_results // max(1, len(query_embeddings))),
        total_results=n_results,
        document_ids=document_ids,
        payload_filters=payload_filters,
    )


def _raw_to_hits(raw: dict) -> tuple[list[SearchResultItem], list[dict]]:
    ids = (raw.get("ids") or [[]])[0]
    documents = (raw.get("documents") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]
    results: list[SearchResultItem] = []
    chunk_dicts: list[dict] = []
    for i in range(len(ids)):
        meta = metadatas[i] if i < len(metadatas) else {}
        doc_id = meta.get("document_id")
        if doc_id is None:
            continue
        chunk_idx = int(meta.get("chunk_index", 0))
        filename = meta.get("filename") or ""
        content = documents[i] if i < len(documents) else ""
        dist = float(distances[i]) if i < len(distances) else 0.0
        score = 1.0 / (1.0 + dist) if dist is not None else 0.0
        pg_s = _opt_positive_int(meta.get("page_start"))
        pg_e = _opt_positive_int(meta.get("page_end"))
        item = SearchResultItem(
            content=content,
            document_id=str(doc_id),
            filename=filename,
            chunk_index=chunk_idx,
            section=meta.get("section") or None,
            breadcrumb=meta.get("breadcrumb") or None,
            page_start=pg_s,
            page_end=pg_e,
            source_url=None,
            distance=dist,
            score=round(score, 4),
        )
        results.append(item)
        chunk_dicts.append({
            "chunk_id": str(ids[i]),
            "content": content,
            "filename": filename,
            "score": score,
            "document_id": str(doc_id),
            "chunk_index": chunk_idx,
            "section": meta.get("section") or "",
            "breadcrumb": meta.get("breadcrumb") or "",
            "distance": dist,
            "page_start": pg_s,
            "page_end": pg_e,
        })
    return results, chunk_dicts


def _merge_hits(
    primary: tuple[list[SearchResultItem], list[dict]],
    secondary: tuple[list[SearchResultItem], list[dict]],
    *,
    max_items: int,
) -> tuple[list[SearchResultItem], list[dict]]:
    p_results, p_chunks = primary
    s_results, s_chunks = secondary
    merged_results: list[SearchResultItem] = []
    merged_chunks: list[dict] = []
    seen: set[str] = set()

    for r, c in list(zip(p_results, p_chunks)) + list(zip(s_results, s_chunks)):
        key = str(c.get("chunk_id") or f"{r.document_id}:{r.chunk_index}")
        if key in seen:
            continue
        seen.add(key)
        merged_results.append(r)
        merged_chunks.append(c)
        if len(merged_results) >= max_items:
            break
    return merged_results, merged_chunks


def _retrieve_with_metadata_first(
    *,
    db: DbSession,
    project_id: str,
    query_text: str,
    queries: list[str],
    n_results: int,
    payload_filters: dict | None = None,
) -> tuple[list[SearchResultItem], list[dict]]:
    candidate_doc_ids = _select_metadata_candidate_doc_ids(db, project_id, query_text)
    scoped_hits: tuple[list[SearchResultItem], list[dict]] = ([], [])
    if candidate_doc_ids:
        scoped_raw = _run_qdrant_retrieval(
            project_id=project_id,
            queries=queries,
            n_results=max(8, n_results),
            document_ids=candidate_doc_ids,
            payload_filters=payload_filters,
        )
        scoped_hits = _raw_to_hits(scoped_raw)

    scoped_results, _ = scoped_hits
    scoped_top3_avg = (
        sum(float(r.score or 0.0) for r in scoped_results[:3]) / min(3, len(scoped_results))
        if scoped_results
        else 0.0
    )
    scoped_good = len(scoped_results) >= 3 and scoped_top3_avg >= 0.55
    if scoped_good and len(scoped_results) >= n_results:
        return scoped_hits

    global_raw = _run_qdrant_retrieval(
        project_id=project_id,
        queries=queries,
        n_results=max(10, n_results),
        payload_filters=payload_filters,
    )
    global_hits = _raw_to_hits(global_raw)
    if not scoped_results:
        return global_hits
    return _merge_hits(scoped_hits, global_hits, max_items=max(10, n_results))


def _finalize_chunks_for_answer(
    query_text: str,
    chunk_dicts: list[dict],
    *,
    search_balance: SearchBalance | None,
    top_k: int,
) -> list[dict]:
    """
    Cross-encoder rerank only (legacy), or weighted fusion of keyword / vector / rerank when
    search_balance is set (matches Search balance UI).
    """
    if search_balance is None:
        return rerank_chunks(query_text, chunk_dicts, top_k=top_k)
    return apply_search_balance_fusion(
        query_text,
        chunk_dicts,
        text_pct=search_balance.text_pct,
        vector_pct=search_balance.vector_pct,
        rerank_pct=search_balance.rerank_pct,
        top_k=top_k,
    )


def _compute_answer_status_and_reason(
    *,
    results_count: int,
    confidence_json: dict | None,
    sources_json: list | None,
    clarification_suggested: bool = False,
    self_check_passed: bool = True,
    self_check_issues: list | None = None,
    missing_info_note: str | None = None,
) -> tuple[str, str | None]:
    """
    Compute answer_status and no_answer_reason for gap analysis.
    Returns (answer_status, no_answer_reason).
    no_answer_reason is set only when answer_status != "answered".
    """
    conf = confidence_json or {}
    overall = conf.get("overall")
    if overall is not None and not isinstance(overall, (int, float)):
        overall = 0.0
    overall = float(overall) if overall is not None else 0.0
    retrieval_avg = float(conf.get("retrieval_avg_top3") or 0)
    evidence_coverage = float(conf.get("evidence_coverage") or 0)
    contradiction_risk = float(conf.get("contradiction_risk") or 0)

    has_usable_sources = bool(sources_json and len(sources_json) > 0)

    # Unanswered: no results, zero confidence, or no usable sources
    if results_count == 0 or overall == 0 or not has_usable_sources:
        reason = "no_results" if results_count == 0 else "insufficient_evidence"
        return "unanswered", reason

    # Needs clarification (reasoning API)
    if clarification_suggested:
        return "needs_clarification", "needs_user_clarification"

    # Contradictory
    if contradiction_risk >= 0.5:
        return "contradictory", "conflicting_sources"

    # Unsupported (self-check found out-of-scope / unsupported)
    issues = self_check_issues or []
    unsupported_keywords = ("out of scope", "unsupported", "not covered", "cannot answer")
    if not self_check_passed and any(
        kw in (issue or "").lower() for issue in issues for kw in unsupported_keywords
    ):
        return "unsupported", "missing_topic"

    # Low confidence
    if overall < 0.5:
        if retrieval_avg < 0.3:
            return "low_confidence", "low_retrieval_score"
        if evidence_coverage < 0.4:
            return "low_confidence", "insufficient_evidence"
        if missing_info_note:
            return "low_confidence", "missing_topic"
        return "low_confidence", "insufficient_evidence"

    if overall < 0.75:
        return "low_confidence", None

    return "answered", None


@router.post("/query", response_model=SearchResponse)
def search(body: SearchRequest, db: DbSession, current_user: CurrentUser):
    """
    Embed the question, search Qdrant for the project's collection,
    return top-k chunks by similarity (question embedding vs stored chunk embeddings).
    Saves the search to search_queries table.
    When advanced_search=True, runs Query Intelligence Layer first (cleanup, intent, split, rewrite, domain, filters, clarification, plan).
    """
    query_text = (body.query_text or "").strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="query_text is required")

    t0 = datetime.now(timezone.utc)
    advanced_search_used = bool(body.advanced_search)
    cleaned_query: str | None = None
    clarification_needed = False
    clarification_questions: list[str] = []
    filters_json = body.filters_json
    queries = [query_text]
    conv_id = _resolve_conversation_id(db, getattr(body, "conversation_id", None))
    conversation_history = _load_recent_conversation_history(db, conv_id)
    sub_questions: list[str] = []

    if body.advanced_search:
        try:
            iq = run_query_intelligence(query_text)
            query_text = iq.cleaned_query or query_text
            cleaned_query = iq.cleaned_query or None
            clarification_needed = iq.clarification_status == "clarification_needed"
            clarification_questions = list(iq.suggested_clarification_questions or [])
            queries = iq.queries_for_retrieval[:6] if iq.queries_for_retrieval else [query_text]
            if iq.filters:
                filters_json = filters_json or {}
                f = iq.filters.model_dump(exclude_none=True)
                extra = f.pop("extra", {})
                if isinstance(extra, dict):
                    filters_json = {**filters_json, **f, **extra}
                else:
                    filters_json = {**filters_json, **f}
        except Exception as e:
            logger.warning("Query intelligence failed, using raw query: %s", e)
        sub_questions = _split_compound_query(query_text)
        contextual_subs = [_build_contextual_query(sq, conversation_history) for sq in sub_questions]
        queries = _merge_query_variants(contextual_subs, queries, max_items=6)

    retrieval_query = _build_contextual_query(query_text, conversation_history)
    if len(queries) == 1:
        queries = [retrieval_query]
    elif retrieval_query != query_text:
        queries = [retrieval_query] + [q for q in queries if q != retrieval_query][:5]

    effective_k = max(int(body.k or 0), 10)
    try:
        results, _ = _retrieve_with_metadata_first(
            db=db,
            project_id=body.project_id,
            query_text=query_text,
            queries=queries,
            n_results=effective_k,
            payload_filters=filters_json,
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=_embedding_failure_detail(e))

    results, _ = _rerank_results_by_metadata(db, body.project_id, query_text, results)

    results = _filter_results_by_confidence(results)
    results = _enrich_results_source_urls(db, body.project_id, results)

    latency_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    try:
        _save_search_query(
            db,
            actor_user_id=current_user.id,
            conversation_id=conv_id,
            query_text=query_text,
            k=effective_k,
            results_count=len(results),
            latency_ms=latency_ms,
            filters_json=filters_json,
        )
        try:
            actor = getattr(current_user, "name", None) or getattr(current_user, "email", None) or "User"
            log_activity(db, actor=actor or "User", event_action="Search query", target_resource=query_text[:200] + ("…" if len(query_text) > 200 else ""), severity="info", system="web")
        except Exception:
            pass
    except Exception as e:
        logger.warning("Failed to save search query to DB: %s", e)

    return SearchResponse(
        query_text=query_text,
        project_id=body.project_id,
        k=effective_k,
        results=results,
        advanced_search_used=advanced_search_used,
        cleaned_query=cleaned_query,
        clarification_needed=clarification_needed,
        clarification_questions=clarification_questions,
    )


@router.post("/answer", response_model=SearchAnswerResponse)
def search_answer(body: SearchRequest, db: DbSession, current_user: CurrentUser):
    """
    Qdrant semantic search → rerank with cross-encoder → GPT synthesis.
    Retrieve more chunks, rerank for accuracy, then synthesize.
    Saves the search to search_queries table.
    When advanced_search=True, runs Query Intelligence Layer first (cleanup, intent, split, rewrite, etc.).
    """
    query_text = (body.query_text or "").strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="query_text is required")

    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="GPT search answer requires OPENAI_API_KEY to be set.",
        )

    t0 = datetime.now(timezone.utc)
    advanced_search_used = bool(body.advanced_search)
    cleaned_query: str | None = None
    clarification_needed = False
    clarification_questions: list[str] = []
    filters_json = body.filters_json
    queries = [query_text]
    conv_id = _resolve_conversation_id(db, getattr(body, "conversation_id", None))
    conversation_history = _load_recent_conversation_history(db, conv_id)
    sub_questions: list[str] = []

    if body.advanced_search:
        try:
            iq = run_query_intelligence(query_text)
            query_text = iq.cleaned_query or query_text
            cleaned_query = iq.cleaned_query or None
            clarification_needed = iq.clarification_status == "clarification_needed"
            clarification_questions = list(iq.suggested_clarification_questions or [])
            queries = iq.queries_for_retrieval[:6] if iq.queries_for_retrieval else [query_text]
            if iq.filters:
                filters_json = filters_json or {}
                f = iq.filters.model_dump(exclude_none=True)
                extra = f.pop("extra", {})
                if isinstance(extra, dict):
                    filters_json = {**filters_json, **f, **extra}
                else:
                    filters_json = {**filters_json, **f}
        except Exception as e:
            logger.warning("Query intelligence failed, using raw query: %s", e)
        sub_questions = _split_compound_query(query_text)

    retrieval_query = _build_contextual_query(query_text, conversation_history)
    if len(queries) == 1:
        queries = [retrieval_query]
    elif retrieval_query != query_text:
        queries = [retrieval_query] + [q for q in queries if q != retrieval_query][:5]

    retrieve_k = min(max(body.k * 2, 15), 25)
    try:
        results, chunk_dicts = _retrieve_with_metadata_first(
            db=db,
            project_id=body.project_id,
            query_text=query_text,
            queries=queries,
            n_results=retrieve_k,
            payload_filters=filters_json,
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=_embedding_failure_detail(e))

    results, reranked_chunks = _rerank_results_by_metadata(
        db, body.project_id, query_text, results, chunk_dicts
    )
    if reranked_chunks is not None:
        chunk_dicts = reranked_chunks

    # Rerank or fuse (Search balance UI: text / vector / rerank weights)
    reranked = _finalize_chunks_for_answer(
        query_text, chunk_dicts, search_balance=body.search_balance, top_k=body.k
    )
    if reranked:
        chunk_dicts = reranked
        results = [
            SearchResultItem(
                content=c.get("content", ""),
                document_id=str(c.get("document_id", "")),
                filename=c.get("filename", ""),
                chunk_index=int(c.get("chunk_index", 0)),
                section=(c.get("section") or None),
                breadcrumb=(c.get("breadcrumb") or None),
                page_start=_opt_positive_int(c.get("page_start")),
                page_end=_opt_positive_int(c.get("page_end")),
                source_url=None,
                distance=c.get("distance", 0.0),
                score=round(c.get("score", 0.0), 4),
            )
            for c in chunk_dicts
        ]

    chunk_dicts = _filter_chunk_dicts_by_confidence(chunk_dicts)
    results = _filter_results_by_confidence(results)
    results = _enrich_results_source_urls(db, body.project_id, results)

    chunks_for_gpt = [
        {"content": c.get("content"), "filename": c.get("filename"), "score": c.get("score")}
        for c in chunk_dicts
    ]
    try:
        synthesis_question = _build_synthesis_question(query_text, sub_questions)
        answer, topics_covered, gpt_confidence = answer_from_chunks(
            synthesis_question, chunks_for_gpt, conversation_history=conversation_history
        )
    except Exception as e:
        print(f"[DEBUG] /search/answer GPT call failed: {type(e).__name__}: {e}")
        logger.exception("GPT search answer failed: %s", e)
        err_msg = str(e).strip() or type(e).__name__
        if "401" in err_msg or "invalid issuer" in err_msg.lower() or "authentication" in err_msg.lower():
            raise HTTPException(
                status_code=503,
                detail="GPT (search answer) auth failed. If using a gateway, set OPENAI_BASE_URL and ensure the token is valid.",
            )
        raise HTTPException(status_code=503, detail=f"GPT answer failed: {err_msg}")

    topic_for_db = ", ".join(topics_covered)[:64] if topics_covered else None
    chroma_ids_for_sources = [f"doc_{r.document_id}_chunk_{r.chunk_index}" for r in results]
    sources = _build_sources(results, chroma_ids_for_sources)
    retrieval_avg_top3 = (
        sum(r.score for r in results[:3]) / min(3, len(results)) if results else 0.0
    )
    confidence = ConfidenceScores(
        overall=gpt_confidence.get("overall", 0),
        retrieval_avg_top3=round(retrieval_avg_top3, 2),
        evidence_coverage=gpt_confidence.get("evidence_coverage", 0),
        contradiction_risk=gpt_confidence.get("contradiction_risk", 0),
    )
    sources_for_db = [s.model_dump() for s in sources]
    confidence_for_db = confidence.model_dump()
    doc_ids = [r.document_id for r in results]
    sources_doc_meta = _build_sources_document_metadata(db, body.project_id, doc_ids)
    answer_status, no_answer_reason = _compute_answer_status_and_reason(
        results_count=len(results),
        confidence_json=confidence_for_db,
        sources_json=sources_for_db,
    )

    latency_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    search_query_id: int | None = None
    conversation_id_out: str | None = None
    try:
        sq_row = _save_search_query(
            db,
            actor_user_id=current_user.id,
            conversation_id=conv_id,
            query_text=query_text,
            k=body.k,
            results_count=len(results),
            latency_ms=latency_ms,
            filters_json=filters_json,
            answer=answer,
            topic=topic_for_db,
            sources_json=sources_for_db,
            confidence_json=confidence_for_db,
            sources_document_metadata_json=sources_doc_meta,
            answer_status=answer_status,
            no_answer_reason=no_answer_reason,
        )
        if sq_row:
            search_query_id = sq_row.id
            conversation_id_out = sq_row.conversation_id
        try:
            actor = getattr(current_user, "name", None) or getattr(current_user, "email", None) or "User"
            log_activity(db, actor=actor, event_action="Search query", target_resource=query_text[:200] + ("…" if len(query_text) > 200 else ""), severity="info", system="web")
        except Exception:
            pass
    except Exception as e:
        logger.warning("Failed to save search query to DB: %s", e)

    return SearchAnswerResponse(
        query_text=query_text,
        project_id=body.project_id,
        k=body.k,
        results=results,
        answer=answer,
        topics_covered=topics_covered,
        sources=sources,
        confidence=confidence,
        search_query_id=search_query_id,
        conversation_id=conversation_id_out,
        advanced_search_used=advanced_search_used,
        cleaned_query=cleaned_query,
        clarification_needed=clarification_needed,
        clarification_questions=clarification_questions,
    )


def _query_text_from_messages(messages: list) -> str:
    """Derive search query from chat messages: last user message, or concatenate all user content."""
    if not messages:
        return ""
    user_parts = []
    for m in messages:
        role = (getattr(m, "role", None) or (m.get("role") if isinstance(m, dict) else "")) or ""
        content = (getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else "")) or ""
        if role == "user" and content:
            user_parts.append(content.strip())
    return user_parts[-1] if user_parts else ""


@router.post("/chat", response_model=SearchChatResponse)
def search_chat(body: SearchChatRequest, db: DbSession, current_user: CurrentUser):
    """
    Chat/completion-style search: request body has `messages` (and project_id, k).
    Uses the last user message as the query, runs semantic search + GPT answer (RAG),
    returns completion-style response with choices[0].message.content and optional results.
    """
    query_text = _query_text_from_messages(body.messages)
    if not query_text:
        raise HTTPException(status_code=400, detail="At least one user message with content is required")

    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="GPT search answer requires OPENAI_API_KEY to be set.",
        )

    t0 = datetime.now(timezone.utc)

    effective_k = max(int(body.k or 0), 10)
    try:
        results, _ = _retrieve_with_metadata_first(
            db=db,
            project_id=body.project_id,
            query_text=query_text,
            queries=[query_text],
            n_results=effective_k,
            payload_filters=body.filters_json,
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=_embedding_failure_detail(e))
    results, _ = _rerank_results_by_metadata(db, body.project_id, query_text, results)

    results = _filter_results_by_confidence(results)
    results = _enrich_results_source_urls(db, body.project_id, results)

    chunks_for_gpt = [
        {"content": r.content, "filename": r.filename, "score": r.score}
        for r in results
    ]
    try:
        answer, topics_covered, gpt_confidence = answer_from_chunks(query_text, chunks_for_gpt)
    except Exception as e:
        logger.exception("GPT search answer failed: %s", e)
        err_msg = str(e).strip() or type(e).__name__
        if "401" in err_msg or "invalid issuer" in err_msg.lower() or "authentication" in err_msg.lower():
            raise HTTPException(
                status_code=503,
                detail="GPT (search answer) auth failed. If using a gateway, set OPENAI_BASE_URL and ensure the token is valid.",
            )
        raise HTTPException(status_code=503, detail=f"GPT answer failed: {err_msg}")

    topic_for_db = ", ".join(topics_covered)[:64] if topics_covered else None
    ids_for_sources = [f"doc_{r.document_id}_chunk_{r.chunk_index}" for r in results]
    sources = _build_sources(results, ids_for_sources)
    retrieval_avg_top3 = (
        sum(r.score for r in results[:3]) / min(3, len(results)) if results else 0.0
    )
    confidence = ConfidenceScores(
        overall=gpt_confidence.get("overall", 0),
        retrieval_avg_top3=round(retrieval_avg_top3, 2),
        evidence_coverage=gpt_confidence.get("evidence_coverage", 0),
        contradiction_risk=gpt_confidence.get("contradiction_risk", 0),
    )
    sources_for_db = [s.model_dump() for s in sources]
    confidence_for_db = confidence.model_dump()
    doc_ids = [r.document_id for r in results]
    sources_doc_meta = _build_sources_document_metadata(db, body.project_id, doc_ids)
    answer_status, no_answer_reason = _compute_answer_status_and_reason(
        results_count=len(results),
        confidence_json=confidence_for_db,
        sources_json=sources_for_db,
    )

    latency_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    conv_id = _resolve_conversation_id(db, getattr(body, "conversation_id", None))
    try:
        _save_search_query(
            db,
            actor_user_id=current_user.id,
            conversation_id=conv_id,
            query_text=query_text,
            k=effective_k,
            results_count=len(results),
            latency_ms=latency_ms,
            filters_json=body.filters_json,
            answer=answer,
            topic=topic_for_db,
            sources_json=sources_for_db,
            confidence_json=confidence_for_db,
            sources_document_metadata_json=sources_doc_meta,
            answer_status=answer_status,
            no_answer_reason=no_answer_reason,
        )
        try:
            actor = getattr(current_user, "name", None) or getattr(current_user, "email", None) or "User"
            log_activity(db, actor=actor, event_action="Search query", target_resource=query_text[:200] + ("…" if len(query_text) > 200 else ""), severity="info", system="web")
        except Exception:
            pass
    except Exception as e:
        logger.warning("Failed to save search query to DB: %s", e)

    return SearchChatResponse(
        id=None,
        choices=[
            {
                "message": {
                    "role": "assistant",
                    "content": answer,
                },
                "index": 0,
            }
        ],
        results=results,
        sources=sources,
        confidence=confidence,
    )


@router.post("/reasoning", response_model=ReasoningResponse)
def search_reasoning(body: ReasoningRequest, db: DbSession, current_user: CurrentUser):
    """
    Agentic RAG pipeline: query understanding → query rewriting → multi-query retrieval
    → evidence bundling → reranking → answer synthesis → self-check.
    When advanced_search=True, uses Query Intelligence Layer (cleanup, intent, split, rewrite, domain, filters, clarification, plan).
    """
    query_text = (body.query_text or "").strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="query_text is required")

    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="Reasoning API requires OPENAI_API_KEY.",
        )

    t0 = datetime.now(timezone.utc)
    advanced_search_used = bool(body.advanced_search)
    cleaned_query: str | None = None
    intelligence_clarification_questions: list[str] = []
    query_analysis: dict = {}
    search_queries: list[str] = [query_text]
    conv_id = _resolve_conversation_id(db, getattr(body, "conversation_id", None))
    conversation_history = _load_recent_conversation_history(db, conv_id)
    sub_questions: list[str] = []

    if body.advanced_search:
        try:
            iq = run_query_intelligence(query_text)
            query_text = iq.cleaned_query or query_text
            cleaned_query = iq.cleaned_query or None
            intelligence_clarification_questions = list(iq.suggested_clarification_questions or [])
            query_analysis = iq.to_query_analysis_dict()
            search_queries = iq.queries_for_retrieval[:6] if iq.queries_for_retrieval else [query_text]
        except Exception as e:
            logger.warning("Query intelligence failed, falling back to analyze_and_rewrite: %s", e)
            try:
                query_analysis, search_queries = analyze_and_rewrite_query(query_text)
            except Exception as e2:
                logger.warning("Query analysis failed, using original: %s", e2)
                search_queries = [query_text]
        sub_questions = _split_compound_query(query_text)
        contextual_subs = [_build_contextual_query(sq, conversation_history) for sq in sub_questions]
        search_queries = _merge_query_variants(contextual_subs, search_queries, max_items=6)
    else:
        try:
            query_analysis, search_queries = analyze_and_rewrite_query(query_text)
        except Exception as e:
            logger.warning("Query analysis failed, using original: %s", e)
            search_queries = [query_text]

    retrieval_query = _build_contextual_query(query_text, conversation_history)
    if retrieval_query != query_text:
        search_queries = [retrieval_query] + [q for q in search_queries if q != retrieval_query][:5]

    retrieve_k = max(int(body.k or 0), 10)
    try:
        results, chunk_dicts = _retrieve_with_metadata_first(
            db=db,
            project_id=body.project_id,
            query_text=query_text,
            queries=search_queries[:6],
            n_results=retrieve_k,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=_embedding_failure_detail(e))

    results, reranked_chunks = _rerank_results_by_metadata(
        db, body.project_id, query_text, results, chunk_dicts
    )
    if reranked_chunks is not None:
        chunk_dicts = reranked_chunks

    # Layer 3: Evidence bundling
    bundled = bundle_evidence(chunk_dicts)

    # Layer 4: Reranking or weighted fusion (Search balance)
    reranked = _finalize_chunks_for_answer(
        query_text, bundled, search_balance=body.search_balance, top_k=body.top_k
    )
    if reranked:
        chunk_dicts = reranked
        results = [
            SearchResultItem(
                content=c.get("content", ""),
                document_id=str(c.get("document_id", "")),
                filename=c.get("filename", ""),
                chunk_index=int(c.get("chunk_index", 0)),
                section=(c.get("section") or None),
                breadcrumb=(c.get("breadcrumb") or None),
                page_start=_opt_positive_int(c.get("page_start")),
                page_end=_opt_positive_int(c.get("page_end")),
                source_url=None,
                distance=c.get("distance", 0.0),
                score=round(c.get("score", 0.0), 4),
            )
            for c in chunk_dicts
        ]

    chunk_dicts = _filter_chunk_dicts_by_confidence(chunk_dicts)
    results = _filter_results_by_confidence(results)
    results = _enrich_results_source_urls(db, body.project_id, results)

    # Answer synthesis
    try:
        synthesis_question = _build_synthesis_question(query_text, sub_questions)
        answer, topics_covered, confidence, uncertainty_note, missing_info_note = (
            reasoning_answer_from_chunks(
                synthesis_question,
                chunk_dicts,
                query_analysis,
                conversation_history=conversation_history,
            )
        )
    except Exception as e:
        logger.exception("Reasoning answer failed: %s", e)
        raise HTTPException(status_code=503, detail=f"Answer synthesis failed: {e}")

    # Layer 5: Self-check
    self_check_passed = True
    self_check_issues: list[str] = []
    clarification_suggested = False

    if not body.skip_self_check and answer:
        try:
            self_check_passed, self_check_issues, clarification_suggested = self_check(
                query_text, answer, chunk_dicts
            )
        except Exception as e:
            logger.warning("Self-check failed: %s", e)

    # Query Intelligence can also suggest clarification
    if intelligence_clarification_questions:
        clarification_suggested = True

    # Build chunk_ids for sources (reranked order may differ from raw ids)
    chroma_ids_for_sources = [
        f"doc_{r.document_id}_chunk_{r.chunk_index}" for r in results
    ]
    sources = _build_sources(results, chroma_ids_for_sources)
    retrieval_avg_top3 = (
        sum(r.score for r in results[:3]) / min(3, len(results)) if results else 0.0
    )
    confidence_obj = ConfidenceScores(
        overall=confidence.get("overall", 0),
        retrieval_avg_top3=round(retrieval_avg_top3, 2),
        evidence_coverage=confidence.get("evidence_coverage", 0),
        contradiction_risk=confidence.get("contradiction_risk", 0),
    )

    analysis_obj = None
    if query_analysis:
        analysis_obj = QueryAnalysis(
            intent=query_analysis.get("intent", ""),
            domain=query_analysis.get("domain", ""),
            answer_type=query_analysis.get("answer_type", ""),
            constraints=query_analysis.get("constraints") or {},
            missing_constraints=query_analysis.get("missing_constraints") or [],
        )

    doc_ids = [r.document_id for r in results]
    sources_doc_meta = _build_sources_document_metadata(db, body.project_id, doc_ids)
    answer_status, no_answer_reason = _compute_answer_status_and_reason(
        results_count=len(results),
        confidence_json=confidence_obj.model_dump(),
        sources_json=[s.model_dump() for s in sources],
        clarification_suggested=clarification_suggested,
        self_check_passed=self_check_passed,
        self_check_issues=self_check_issues,
        missing_info_note=missing_info_note,
    )
    latency_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    search_query_id: int | None = None
    conversation_id_out: str | None = None
    try:
        sq_row = save_reasoning_search(
            db,
            actor_user_id=current_user.id,
            conversation_id=conv_id,
            query_text=query_text,
            k=retrieve_k,
            results_count=len(results),
            latency_ms=latency_ms,
            answer=answer,
            topic=", ".join(topics_covered)[:64] if topics_covered else None,
            sources_json=[s.model_dump() for s in sources],
            confidence_json=confidence_obj.model_dump(),
            sources_document_metadata_json=sources_doc_meta,
            answer_status=answer_status,
            no_answer_reason=no_answer_reason,
        )
        if sq_row:
            search_query_id = sq_row.id
            conversation_id_out = sq_row.conversation_id
        try:
            actor = getattr(current_user, "name", None) or getattr(current_user, "email", None) or "User"
            log_activity(db, actor=actor, event_action="Search query", target_resource=query_text[:200] + ("…" if len(query_text) > 200 else ""), severity="info", system="web")
        except Exception:
            pass
    except Exception as e:
        logger.warning("Failed to save reasoning search to DB: %s", e)

    return ReasoningResponse(
        query_text=query_text,
        project_id=body.project_id,
        results=results,
        answer=answer,
        conversation_id=conversation_id_out,
        topics_covered=topics_covered,
        sources=sources,
        confidence=confidence_obj,
        uncertainty_note=uncertainty_note,
        missing_info_note=missing_info_note,
        query_analysis=analysis_obj,
        self_check_passed=self_check_passed,
        self_check_issues=self_check_issues,
        clarification_suggested=clarification_suggested,
        clarification_questions=intelligence_clarification_questions,
        search_query_id=search_query_id,
        advanced_search_used=advanced_search_used,
        cleaned_query=cleaned_query,
    )


def _sse(event: str, data: dict) -> str:
    """Format one Server-Sent Event (event + data as JSON, one line)."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _reasoning_stream_generator(
    body: ReasoningRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    """
    Generator that runs the reasoning pipeline and yields SSE events.
    Same logic as search_reasoning, with status/search_query/confidence/result events.
    When advanced_search=True, uses Query Intelligence Layer.
    """
    query_text = (body.query_text or "").strip()
    t0 = datetime.now(timezone.utc)
    advanced_search_used = bool(body.advanced_search)
    cleaned_query: str | None = None
    intelligence_clarification_questions: list[str] = []
    query_analysis: dict = {}
    search_queries: list[str] = [query_text]
    conv_id = _resolve_conversation_id(db, getattr(body, "conversation_id", None))
    conversation_history = _load_recent_conversation_history(db, conv_id)
    sub_questions: list[str] = []

    try:
        yield _sse("status", {"step": "thinking", "message": "Analyzing your question..."})

        if body.advanced_search:
            try:
                iq = run_query_intelligence(query_text)
                query_text = iq.cleaned_query or query_text
                cleaned_query = iq.cleaned_query or None
                intelligence_clarification_questions = list(iq.suggested_clarification_questions or [])
                query_analysis = iq.to_query_analysis_dict()
                search_queries = iq.queries_for_retrieval[:6] if iq.queries_for_retrieval else [query_text]
            except Exception as e:
                logger.warning("Query intelligence failed in stream, falling back: %s", e)
                try:
                    query_analysis, search_queries = analyze_and_rewrite_query(query_text)
                except Exception:
                    search_queries = [query_text]
            sub_questions = _split_compound_query(query_text)
            contextual_subs = [_build_contextual_query(sq, conversation_history) for sq in sub_questions]
            search_queries = _merge_query_variants(contextual_subs, search_queries, max_items=6)
        else:
            try:
                query_analysis, search_queries = analyze_and_rewrite_query(query_text)
            except Exception as e:
                logger.warning("Query analysis failed, using original: %s", e)
                search_queries = [query_text]

        retrieval_query = _build_contextual_query(query_text, conversation_history)
        if retrieval_query != query_text:
            search_queries = [retrieval_query] + [q for q in search_queries if q != retrieval_query][:5]

        if query_analysis:
            yield _sse("query_analysis", {
                "intent": query_analysis.get("intent", ""),
                "domain": query_analysis.get("domain", ""),
                "answer_type": query_analysis.get("answer_type", ""),
            })

        total = len(search_queries)
        for idx, q in enumerate(search_queries[:6], 1):
            yield _sse("search_query", {"query": q, "index": idx, "total": total})

        yield _sse("status", {"step": "retrieval", "message": "Searching documents..."})

        retrieve_k = max(int(body.k or 0), 10)
        results, chunk_dicts = _retrieve_with_metadata_first(
            db=db,
            project_id=body.project_id,
            query_text=query_text,
            queries=search_queries[:6],
            n_results=retrieve_k,
        )

        results, reranked_chunks = _rerank_results_by_metadata(
            db, body.project_id, query_text, results, chunk_dicts
        )
        if reranked_chunks is not None:
            chunk_dicts = reranked_chunks

        bundled = bundle_evidence(chunk_dicts)

        yield _sse("status", {"step": "reranking", "message": "Reranking results..."})

        reranked = _finalize_chunks_for_answer(
            query_text, bundled, search_balance=body.search_balance, top_k=body.top_k
        )
        if reranked:
            chunk_dicts = reranked
            results = [
                SearchResultItem(
                    content=c.get("content", ""),
                    document_id=str(c.get("document_id", "")),
                    filename=c.get("filename", ""),
                    chunk_index=int(c.get("chunk_index", 0)),
                    section=(c.get("section") or None),
                    breadcrumb=(c.get("breadcrumb") or None),
                    page_start=_opt_positive_int(c.get("page_start")),
                    page_end=_opt_positive_int(c.get("page_end")),
                    source_url=None,
                    distance=c.get("distance", 0.0),
                    score=round(c.get("score", 0.0), 4),
                )
                for c in chunk_dicts
            ]

        chunk_dicts = _filter_chunk_dicts_by_confidence(chunk_dicts)
        results = _filter_results_by_confidence(results)
        results = _enrich_results_source_urls(db, body.project_id, results)

        # Emit search results for the reasoning log (questions + results)
        search_results_payload = {
            "total": len(results),
            "items": [
                {
                    "filename": r.filename,
                    "score": round(r.score, 4),
                    "preview": (r.content[:150] + "…") if len(r.content) > 150 else r.content,
                }
                for r in results[:20]
            ],
        }
        yield _sse("search_results", search_results_payload)

        yield _sse("status", {"step": "synthesizing", "message": "Synthesizing answer..."})

        synthesis_question = _build_synthesis_question(query_text, sub_questions)
        answer, topics_covered, confidence, uncertainty_note, missing_info_note = (
            reasoning_answer_from_chunks(
                synthesis_question,
                chunk_dicts,
                query_analysis,
                conversation_history=conversation_history,
            )
        )

        # Self-check
        self_check_passed = True
        self_check_issues_list: list[str] = []
        clarification_suggested = False
        if not body.skip_self_check and answer:
            try:
                self_check_passed, self_check_issues_list, clarification_suggested = self_check(
                    query_text, answer, chunk_dicts
                )
            except Exception as e:
                logger.warning("Self-check failed: %s", e)
        if intelligence_clarification_questions:
            clarification_suggested = True

        chroma_ids_for_sources = [
            f"doc_{r.document_id}_chunk_{r.chunk_index}" for r in results
        ]
        sources = _build_sources(results, chroma_ids_for_sources)
        retrieval_avg_top3 = (
            sum(r.score for r in results[:3]) / min(3, len(results)) if results else 0.0
        )
        confidence_obj = ConfidenceScores(
            overall=confidence.get("overall", 0),
            retrieval_avg_top3=round(retrieval_avg_top3, 2),
            evidence_coverage=confidence.get("evidence_coverage", 0),
            contradiction_risk=confidence.get("contradiction_risk", 0),
        )

        yield _sse("confidence", confidence_obj.model_dump())

        analysis_obj = None
        if query_analysis:
            analysis_obj = QueryAnalysis(
                intent=query_analysis.get("intent", ""),
                domain=query_analysis.get("domain", ""),
                answer_type=query_analysis.get("answer_type", ""),
                constraints=query_analysis.get("constraints") or {},
                missing_constraints=query_analysis.get("missing_constraints") or [],
            )

        doc_ids = [r.document_id for r in results]
        sources_doc_meta = _build_sources_document_metadata(db, body.project_id, doc_ids)
        answer_status, no_answer_reason = _compute_answer_status_and_reason(
            results_count=len(results),
            confidence_json=confidence_obj.model_dump(),
            sources_json=[s.model_dump() for s in sources],
            clarification_suggested=clarification_suggested,
            self_check_passed=self_check_passed,
            self_check_issues=self_check_issues_list,
            missing_info_note=missing_info_note,
        )
        latency_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
        search_query_id: int | None = None
        conversation_id_out: str | None = None
        try:
            sq_row = save_reasoning_search(
                db,
                actor_user_id=current_user.id,
                conversation_id=conv_id,
                query_text=query_text,
                k=retrieve_k,
                results_count=len(results),
                latency_ms=latency_ms,
                answer=answer,
                topic=", ".join(topics_covered)[:64] if topics_covered else None,
                sources_json=[s.model_dump() for s in sources],
                confidence_json=confidence_obj.model_dump(),
                sources_document_metadata_json=sources_doc_meta,
                answer_status=answer_status,
                no_answer_reason=no_answer_reason,
            )
            if sq_row:
                search_query_id = sq_row.id
                conversation_id_out = sq_row.conversation_id
            try:
                actor = getattr(current_user, "name", None) or getattr(current_user, "email", None) or "User"
                log_activity(db, actor=actor, event_action="Search query", target_resource=query_text[:200] + ("…" if len(query_text) > 200 else ""), severity="info", system="web")
            except Exception:
                pass
        except Exception as e:
            logger.warning("Failed to save reasoning search to DB: %s", e)

        response = ReasoningResponse(
            query_text=query_text,
            project_id=body.project_id,
            results=results,
            answer=answer,
            conversation_id=conversation_id_out,
            topics_covered=topics_covered,
            sources=sources,
            confidence=confidence_obj,
            uncertainty_note=uncertainty_note,
            missing_info_note=missing_info_note,
            query_analysis=analysis_obj,
            self_check_passed=self_check_passed,
            self_check_issues=self_check_issues_list,
            clarification_suggested=clarification_suggested,
            clarification_questions=intelligence_clarification_questions,
            search_query_id=search_query_id,
            advanced_search_used=advanced_search_used,
            cleaned_query=cleaned_query,
        )
        yield _sse("result", response.model_dump(mode="json"))

    except Exception as e:
        logger.exception("Reasoning stream failed: %s", e)
        yield _sse("error", {"detail": str(e)})


@router.post("/reasoning/stream")
def search_reasoning_stream(body: ReasoningRequest, db: DbSession, current_user: CurrentUser):
    """
    Same as POST /reasoning but returns Server-Sent Events: status, query_analysis,
    search_query (per generated query), confidence, then result (full ReasoningResponse).
    """
    query_text = (body.query_text or "").strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="query_text is required")
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Reasoning API requires OPENAI_API_KEY.")

    return StreamingResponse(
        _reasoning_stream_generator(body, db, current_user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_time_ago(dt: datetime) -> str:
    """Human-readable relative time (e.g. '2 min ago', '1 hour ago')."""
    if not dt:
        return ""
    now = datetime.now(timezone.utc)
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    secs = delta.total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        m = int(secs // 60)
        return f"{m} min ago" if m == 1 else f"{m} min ago"
    if secs < 86400:
        h = int(secs // 3600)
        return f"{h} hour ago" if h == 1 else f"{h} hours ago"
    d = int(secs // 86400)
    return f"{d} day ago" if d == 1 else f"{d} days ago"


def _format_size(bytes_val: int) -> str:
    """Human-readable size (e.g. '2.4 MB')."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    if bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    return f"{bytes_val / (1024 * 1024):.1f} MB"


@router.get("/intelligence", response_model=IntelligenceHubResponse)
def get_intelligence_hub(
    db: DbSession,
    current_user: CurrentUserOptional,
    project_id: str | None = None,
):
    """
    Intelligence Hub dashboard data from search_queries and documents.
    - most_searched_topics: from search_queries.topic (comma-separated values split and counted)
    - low_confidence_areas: queries where confidence_json.overall < 0.75
    - gaps_in_knowledge: queries with 0 results (high) or low confidence (medium/low)
    - recently_uploaded: latest documents from the project
    """
    require_admin_only(current_user)
    # Resolve project: use first non-deleted if not specified
    pid = project_id
    if not pid:
        row = db.execute(select(Project.id).where(Project.is_deleted == False).limit(1)).first()
        pid = row[0] if row else None

    most_searched: list[IntelligenceHubTopic] = []
    low_confidence: list[IntelligenceHubLowConfidence] = []
    high_confidence: list[IntelligenceHubHighConfidence] = []
    gaps: list[IntelligenceHubGap] = []
    recent_docs: list[IntelligenceHubRecentDoc] = []

    if pid:
        # Fetch recent search queries (last 30 days) for aggregation (search_queries are global; no project_id)
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        q = (
            select(SearchQuery)
            .where(SearchQuery.datetime_ >= cutoff)
            .order_by(SearchQuery.datetime_.desc())
            .limit(500)
        )
        queries = list(db.execute(q).scalars().all())

        # Most searched topics: count by topic column (comma-separated values split and counted)
        topic_counts: Counter[str] = Counter()
        for sq in queries:
            topic_str = (sq.topic or "").strip()
            if topic_str:
                for t in topic_str.split(","):
                    t = t.strip()
                    if t:
                        topic_counts[t] += 1
            else:
                # Fallback to query_text when topic is empty (e.g. from /search/query)
                text = (sq.query_text or "").strip()
                if text:
                    topic_counts[text] += 1
        most_searched = [
            IntelligenceHubTopic(topic=t, count=c)
            for t, c in topic_counts.most_common(5)
        ]

        # Low confidence: confidence_json.overall < 0.75 (topic or query for section label)
        for sq in queries:
            conf = sq.confidence_json or {}
            overall = conf.get("overall")
            if overall is not None and isinstance(overall, (int, float)) and overall < 0.75:
                section = (sq.topic or sq.query_text or "").strip()[:80] or "Unknown query"
                low_confidence.append(
                    IntelligenceHubLowConfidence(section=section, confidence=int(round(overall * 100)))
                )
        low_confidence = low_confidence[:10]  # limit

        # High confidence: confidence_json.overall >= 0.85 — by topic/section, keep max confidence
        section_best: dict[str, int] = {}
        for sq in queries:
            conf = sq.confidence_json or {}
            overall = conf.get("overall")
            if overall is not None and isinstance(overall, (int, float)) and overall >= 0.85:
                section = (sq.topic or sq.query_text or "").strip()[:80] or "Unknown query"
                pct = int(round(overall * 100))
                if section not in section_best or pct > section_best[section]:
                    section_best[section] = pct
        high_confidence = [
            IntelligenceHubHighConfidence(section=s, confidence=c)
            for s, c in sorted(section_best.items(), key=lambda x: -x[1])[:5]
        ]

        # Gaps in knowledge: data lacking in documents — use answer_status and no_answer_reason
        # high: no_results, missing_topic, insufficient_evidence (documents don't cover this)
        # medium: low_retrieval_score, unanswered, low_confidence
        # low: few results or low confidence but answered
        for sq in queries:
            area = (sq.topic or sq.query_text or "")[:60] or "Unknown"
            reason = (sq.no_answer_reason or "").strip()
            status = (sq.answer_status or "").strip()
            if sq.results_count == 0:
                gaps.append(IntelligenceHubGap(area=area, priority="high"))
            elif reason in ("no_results", "missing_topic", "insufficient_evidence"):
                gaps.append(IntelligenceHubGap(area=area, priority="high"))
            elif status in ("unanswered", "low_confidence") or reason in ("low_retrieval_score", "conflicting_sources"):
                gaps.append(IntelligenceHubGap(area=area, priority="medium"))
            else:
                conf = sq.confidence_json or {}
                overall = conf.get("overall")
                if overall is not None and isinstance(overall, (int, float)) and overall < 0.65:
                    gaps.append(IntelligenceHubGap(area=area, priority="low"))
        gaps = list({g.area: g for g in gaps}.values())[:10]  # dedupe by area, limit

        # Recently uploaded documents
        doc_q = (
            select(Document)
            .where(Document.project_id == pid, Document.deleted_at.is_(None))
            .order_by(Document.uploaded_at.desc())
            .limit(6)
        )
        doc_rows = list(db.execute(doc_q).scalars().all())
        for doc in doc_rows:
            recent_docs.append(
                IntelligenceHubRecentDoc(
                    id=doc.id,
                    name=doc.filename,
                    time=_format_time_ago(doc.uploaded_at),
                    size=_format_size(doc.size_bytes),
                )
            )

    # Index health: only when we have a project
    index_health: IndexHealth | None = None
    if pid:
        total_docs = db.execute(
            select(func.count()).select_from(Document).where(
                Document.project_id == pid, Document.deleted_at.is_(None)
            )
        ).scalar() or 0
        ingested_count = db.execute(
            select(func.count()).select_from(Document).where(
                Document.project_id == pid,
                Document.deleted_at.is_(None),
                Document.status == DocumentStatus.ingested,
            )
        ).scalar() or 0
        documents_indexed_pct = int(round((ingested_count / total_docs * 100))) if total_docs else 0
        chunks_in_vector_db = get_collection_count(pid)
        last_indexed_ago = None
        last_row = db.execute(
            select(Document.ingested_at)
            .where(
                Document.project_id == pid,
                Document.deleted_at.is_(None),
                Document.status == DocumentStatus.ingested,
                Document.ingested_at.isnot(None),
            )
            .order_by(Document.ingested_at.desc())
            .limit(1)
        ).first()
        if last_row and last_row[0]:
            last_indexed_ago = _format_time_ago(last_row[0])
        if documents_indexed_pct >= 90 and chunks_in_vector_db > 0:
            embedding_quality = "Good"
        elif documents_indexed_pct >= 50 or chunks_in_vector_db > 0:
            embedding_quality = "Fair"
        else:
            embedding_quality = "Poor"
        index_health = IndexHealth(
            documents_indexed_pct=documents_indexed_pct,
            chunks_in_vector_db=chunks_in_vector_db,
            embedding_quality=embedding_quality,
            last_indexed_ago=last_indexed_ago,
        )

    return IntelligenceHubResponse(
        most_searched_topics=most_searched,
        low_confidence_areas=low_confidence,
        high_confidence_areas=high_confidence,
        gaps_in_knowledge=gaps,
        recently_uploaded=recent_docs,
        index_health=index_health,
    )


@router.get("/queries", response_model=list[SearchQueryResponse])
def list_search_queries(
    db: DbSession,
    current_user: CurrentUserOptional,
    project_id: str | None = None,
    on_date: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """List search queries (Conversation Log). Admin/Super Admin only. Use from_date and to_date (YYYY-MM-DD) for a range, or on_date for a single day. Default: today."""
    require_admin_only(current_user)
    now = datetime.now(timezone.utc).date()
    try:
        if from_date and to_date:
            start_date = date.fromisoformat(from_date)
            end_date = date.fromisoformat(to_date)
            if start_date > end_date:
                start_date, end_date = end_date, start_date
            day_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
            day_end = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, 999999, tzinfo=timezone.utc)
            end_inclusive = True
        elif on_date is not None:
            filter_date = date.fromisoformat(on_date)
            day_start = datetime(filter_date.year, filter_date.month, filter_date.day, tzinfo=timezone.utc)
            day_end = day_start + timedelta(days=1)
            end_inclusive = False
        else:
            day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
            day_end = day_start + timedelta(days=1)
            end_inclusive = False
    except (ValueError, TypeError):
        day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        end_inclusive = False
    if end_inclusive:
        q = (
            select(SearchQuery)
            .where(SearchQuery.datetime_ >= day_start, SearchQuery.datetime_ <= day_end)
            .order_by(SearchQuery.datetime_.desc())
            .offset(skip)
            .limit(limit)
        )
    else:
        q = (
            select(SearchQuery)
            .where(SearchQuery.datetime_ >= day_start, SearchQuery.datetime_ < day_end)
            .order_by(SearchQuery.datetime_.desc())
            .offset(skip)
            .limit(limit)
        )
    rows = db.execute(q).scalars().all()
    return list(rows)


@router.get("/queries/{search_query_id}", response_model=SearchQueryResponse)
def get_search_query(search_query_id: int, db: DbSession, current_user: CurrentUserOptional):
    """Get a single search query by id (for conversation log detail). Admin/Super Admin only."""
    require_admin_only(current_user)
    sq = db.execute(select(SearchQuery).where(SearchQuery.id == search_query_id)).scalars().one_or_none()
    if not sq:
        raise HTTPException(status_code=404, detail="Search query not found")
    return sq


@router.get("/queries/by-conversation/{conversation_id}", response_model=list[SearchQueryResponse])
def list_search_queries_by_conversation(conversation_id: str, db: DbSession, current_user: CurrentUserOptional):
    """List all search queries (Q&A pairs) for a conversation, ordered by time. Admin/Super Admin only. Use for conversation log detail."""
    require_admin_only(current_user)
    q = (
        select(SearchQuery)
        .where(SearchQuery.conversation_id == conversation_id)
        .order_by(SearchQuery.datetime_.asc())
    )
    rows = db.execute(q).scalars().all()
    return list(rows)


@router.patch("/queries/{search_query_id}/feedback", response_model=SearchQueryResponse)
def submit_search_feedback(
    search_query_id: int,
    body: SearchFeedbackRequest,
    db: DbSession,
    current_user: CurrentUserOptional,
):
    """Submit or update feedback for a search query. Overwrites any existing feedback."""
    sq = db.execute(select(SearchQuery).where(SearchQuery.id == search_query_id)).scalars().one_or_none()
    if not sq:
        raise HTTPException(status_code=404, detail="Search query not found")
    sq.feedback_status = body.feedback_status
    sq.feedback_score = body.feedback_score
    sq.feedback_reason = body.feedback_reason
    sq.feedback_text = body.feedback_text
    sq.feedback_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(sq)
    return sq
