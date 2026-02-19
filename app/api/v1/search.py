"""Search API — semantic search via ChromaDB (question embedding vs document embeddings)."""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from app.api.deps import DbSession, CurrentUserOptional

from app.models.search_query import SearchQuery
from app.schemas.search import SearchRequest, SearchResponse, SearchResultItem, SearchQueryResponse, SearchAnswerResponse
from app.services.embeddings import get_embedding
from app.services.chroma import query_collection
from app.services.search_answer import answer_from_chunks
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


def _save_search_query(
    db: DbSession,
    *,
    actor_user_id: uuid.UUID | None,
    project_id: int,
    query_text: str,
    k: int,
    results_count: int,
    latency_ms: int | None,
    filters_json: dict | None = None,
    answer: str | None = None,
) -> None:
    """Persist one search to search_queries table. answer is set when using /search/answer (RAG)."""
    row = SearchQuery(
        ts=datetime.now(timezone.utc),
        actor_user_id=actor_user_id,
        project_id=project_id,
        query_text=query_text,
        k=k,
        filters_json=filters_json,
        results_count=results_count,
        latency_ms=latency_ms,
        answer=answer,
    )
    db.add(row)
    db.commit()


@router.post("/query", response_model=SearchResponse)
def search(body: SearchRequest, db: DbSession, current_user: CurrentUserOptional):
    """
    Embed the question, search ChromaDB for the project's collection,
    return top-k chunks by similarity (question embedding vs stored chunk embeddings).
    Saves the search to search_queries table.
    """
    query_text = (body.query_text or "").strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="query_text is required")

    t0 = datetime.now(timezone.utc)

    try:
        query_embedding = get_embedding(query_text)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))

    raw = query_collection(
        project_id=body.project_id,
        query_embedding=query_embedding,
        n_results=body.k,
    )

    # Chroma returns lists of lists (one per query); we sent one query
    ids = (raw.get("ids") or [[]])[0]
    documents = (raw.get("documents") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    results: list[SearchResultItem] = []
    for i in range(len(ids)):
        meta = metadatas[i] if i < len(metadatas) else {}
        doc_id = meta.get("document_id")
        chunk_idx = meta.get("chunk_index", 0)
        filename = meta.get("filename") or ""
        content = documents[i] if i < len(documents) else ""
        dist = float(distances[i]) if i < len(distances) else 0.0
        # ChromaDB L2 distance: lower = more similar. Convert to score in [0,1]: 1 / (1 + distance)
        score = 1.0 / (1.0 + dist) if dist is not None else 0.0
        if doc_id is not None:
            results.append(
                SearchResultItem(
                    content=content,
                    document_id=int(doc_id),
                    filename=filename,
                    chunk_index=int(chunk_idx),
                    distance=dist,
                    score=round(score, 4),
                )
            )

    latency_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    try:
        _save_search_query(
            db,
            actor_user_id=current_user.id if current_user else None,
            project_id=body.project_id,
            query_text=query_text,
            k=body.k,
            results_count=len(results),
            latency_ms=latency_ms,
            filters_json=body.filters_json,
        )
    except Exception as e:
        logger.warning("Failed to save search query to DB: %s", e)

    return SearchResponse(
        query_text=query_text,
        project_id=body.project_id,
        k=body.k,
        results=results,
    )


@router.post("/answer", response_model=SearchAnswerResponse)
def search_answer(body: SearchRequest, db: DbSession, current_user: CurrentUserOptional):
    """
    Same as /query (ChromaDB semantic search), then use GPT to synthesize
    a natural-language answer from the top-k chunks (RAG).
    Saves the search to search_queries table.
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

    try:
        query_embedding = get_embedding(query_text)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))

    raw = query_collection(
        project_id=body.project_id,
        query_embedding=query_embedding,
        n_results=body.k,
    )

    ids = (raw.get("ids") or [[]])[0]
    documents = (raw.get("documents") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    results: list[SearchResultItem] = []
    for i in range(len(ids)):
        meta = metadatas[i] if i < len(metadatas) else {}
        doc_id = meta.get("document_id")
        chunk_idx = meta.get("chunk_index", 0)
        filename = meta.get("filename") or ""
        content = documents[i] if i < len(documents) else ""
        dist = float(distances[i]) if i < len(distances) else 0.0
        score = 1.0 / (1.0 + dist) if dist is not None else 0.0
        if doc_id is not None:
            results.append(
                SearchResultItem(
                    content=content,
                    document_id=int(doc_id),
                    filename=filename,
                    chunk_index=int(chunk_idx),
                    distance=dist,
                    score=round(score, 4),
                )
            )

    chunks_for_gpt = [
        {"content": r.content, "filename": r.filename, "score": r.score}
        for r in results
    ]
    try:
        answer = answer_from_chunks(query_text, chunks_for_gpt)
    except Exception as e:
        logger.exception("GPT search answer failed: %s", e)
        raise HTTPException(status_code=503, detail=f"GPT answer failed: {e!s}")

    latency_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    try:
        _save_search_query(
            db,
            actor_user_id=current_user.id if current_user else None,
            project_id=body.project_id,
            query_text=query_text,
            k=body.k,
            results_count=len(results),
            latency_ms=latency_ms,
            filters_json=body.filters_json,
            answer=answer,
        )
    except Exception as e:
        logger.warning("Failed to save search query to DB: %s", e)

    return SearchAnswerResponse(
        query_text=query_text,
        project_id=body.project_id,
        k=body.k,
        results=results,
        answer=answer,
    )


@router.get("/queries", response_model=list[SearchQueryResponse])
def list_search_queries(db: DbSession, project_id: int | None = None, skip: int = 0, limit: int = 100):
    """List recent search queries. TODO: add auth, filter by user/project."""
    raise NotImplementedError("TODO: implement list search queries")
