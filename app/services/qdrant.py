"""Qdrant vector store for project-scoped chunk search and upserts.

Public entry points match the previous Chroma-shaped API (`query_collection` return shape)
so search, advanced search, and reasoning layers stay unchanged.
"""
from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.config import settings
from app.services.embeddings import get_embedding

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_qdrant_client = None
_VECTOR_SIZE_CACHE: dict[str, int] = {}
_SPARSE_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_\-\.]{1,63}")
_RRF_K = 60
_BRANCH_EXPANSION = 4
_SPARSE_SCAN_CAP = 500


def _tokenize_sparse(text: str) -> list[str]:
    return _SPARSE_TOKEN_RE.findall((text or "").lower())


def _sparse_terms(text: str, max_terms: int = 64) -> list[dict]:
    tokens = _tokenize_sparse(text)
    if not tokens:
        return []
    counts = Counter(tokens)
    total = float(sum(counts.values()) or 1.0)
    ranked = counts.most_common(max_terms)
    return [{"t": t, "w": round(c / total, 6)} for t, c in ranked]


def _sparse_query_map(query_text: str) -> dict[str, float]:
    tokens = _tokenize_sparse(query_text)
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = float(sum(counts.values()) or 1.0)
    return {t: c / total for t, c in counts.items()}


def _sparse_overlap_score(query_weights: dict[str, float], chunk_terms: list[dict]) -> float:
    if not query_weights or not chunk_terms:
        return 0.0
    score = 0.0
    for term in chunk_terms:
        tok = str(term.get("t") or "")
        if not tok:
            continue
        qw = float(query_weights.get(tok) or 0.0)
        if qw <= 0:
            continue
        tw = float(term.get("w") or 0.0)
        score += min(qw, tw if tw > 0 else 0.0)
    return max(0.0, min(1.0, score))


def _point_id(document_id: str, chunk_index: int) -> str:
    """
    Qdrant point id must be uint64 or UUID.
    Use deterministic UUID5 so upserts are stable across re-index runs.
    """
    seed = f"{document_id}:{chunk_index}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def get_qdrant_client():
    """
    Return shared Qdrant client.

    - If ``QDRANT_LOCAL_PATH`` is set: embedded storage on disk (``QdrantClient(path=...)``),
      same pattern as ``pdf_qdrant_api.py`` / ``--path`` — no separate Qdrant process.
    - Otherwise: HTTP client to ``QDRANT_URL`` (e.g. local server or cloud).
    """
    global _qdrant_client
    if _qdrant_client is None:
        raw = (settings.qdrant_local_path or "").strip()
        # Disable embedded mode: use HTTP QDRANT_URL (Cloud or local server).
        if raw.lower() in ("-", "none", "remote", "0", "false", "http", "url"):
            local = ""
        else:
            local = raw
        if local:
            p = Path(local).expanduser()
            if not p.is_absolute():
                p = _BACKEND_ROOT / p
            p.mkdir(parents=True, exist_ok=True)
            try:
                _qdrant_client = QdrantClient(path=str(p.resolve()))
            except Exception as e:
                # Common on Windows when another process already opened embedded storage.
                # Fall back to HTTP client so concurrent app processes can still use Qdrant.
                err = str(e).lower()
                if "already accessed by another instance" not in err and "alreadylocked" not in err:
                    raise
                url = (settings.qdrant_url or "").strip() or "http://127.0.0.1:6333"
                api_key = (settings.qdrant_api_key or "").strip() or None
                _qdrant_client = QdrantClient(
                    url=url,
                    api_key=api_key,
                    timeout=settings.qdrant_timeout_sec,
                    check_compatibility=False,
                )
        else:
            url = (settings.qdrant_url or "").strip() or "http://127.0.0.1:6333"
            api_key = (settings.qdrant_api_key or "").strip() or None
            _qdrant_client = QdrantClient(
                url=url,
                api_key=api_key,
                timeout=settings.qdrant_timeout_sec,
                check_compatibility=False,
            )
    return _qdrant_client


def get_chroma_client():
    """Backward-compatible name used by older imports."""
    return get_qdrant_client()


def _collection_name(folder_id: str | int) -> str:
    """Stable collection name for a folder/project."""
    raw = str(folder_id).strip().replace("-", "_")
    prefix = (settings.qdrant_collection_prefix or "folder").strip() or "folder"
    return f"{prefix}_{raw}"


def _vector_size_from_collection_config(vectors: object) -> int:
    if vectors is None:
        raise ValueError("Collection has no vectors config.")
    if isinstance(vectors, dict):
        first = next(iter(vectors.values()))
        return int(first.size)
    return int(vectors.size)


def _name_slug_for_collection(display_name: str, max_len: int = 48) -> str:
    """Safe fragment for Qdrant collection names (letters, digits, underscore)."""
    raw = re.sub(r"[^a-zA-Z0-9]+", "_", (display_name or "user").strip().lower()).strip("_")
    return (raw[:max_len] if raw else "user")


def user_vector_collection_name(user_id: str, display_name: str) -> str:
    """
    Stable Qdrant collection name for a user: prefix + name slug + user id (unique).
    Stored in User.vector_database after provisioning.
    """
    prefix = (settings.qdrant_user_collection_prefix or "vd").strip() or "vd"
    slug = _name_slug_for_collection(display_name)
    uid = str(user_id).strip().replace("-", "_")
    return f"{prefix}_{slug}_{uid}"


def ensure_named_vector_collection(collection_name: str, vector_size: int) -> None:
    """Create a Qdrant collection if missing (cosine, same as project folders)."""
    client = get_qdrant_client()
    name = collection_name.strip()
    if not name:
        raise ValueError("collection_name is required")
    if not client.collection_exists(name):
        try:
            client.create_collection(
                collection_name=name,
                vectors_config={"dense": VectorParams(size=int(vector_size), distance=Distance.COSINE)},
            )
        except Exception:
            # Backward-compatible fallback for older collections/client behavior.
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=int(vector_size), distance=Distance.COSINE),
            )
    _VECTOR_SIZE_CACHE[name] = int(vector_size)


def provision_user_vector_database(
    user_id: str,
    display_name: str,
    stored_collection_name: str | None,
) -> str:
    """
    Ensure a per-user Qdrant collection exists and return its name for User.vector_database.
    Reuses stored name when set so re-provisioning does not orphan collections.
    """
    target = (stored_collection_name or "").strip() or user_vector_collection_name(user_id, display_name)
    vector_size = _infer_vector_size([" "], None)
    ensure_named_vector_collection(target, vector_size)
    return target


def _infer_vector_size(chunks: list[str], embeddings: list[list[float]] | None) -> int:
    if embeddings and isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
        return len(embeddings[0])
    if not chunks:
        raise ValueError("Cannot infer vector size: no chunks provided.")
    sample = get_embedding(chunks[0])
    if not sample:
        raise ValueError("Embedding function returned empty vector.")
    return len(sample)


def _ensure_collection(folder_id: str | int, vector_size: int) -> str:
    name = _collection_name(folder_id)
    ensure_named_vector_collection(name, vector_size)
    return name


def _ensure_collection_for_upsert(
    folder_id: str | int,
    chunks: list[str],
    embeddings: list[list[float]] | None,
) -> str:
    client = get_qdrant_client()
    name = _collection_name(folder_id)
    if client.collection_exists(name):
        if name not in _VECTOR_SIZE_CACHE:
            info = client.get_collection(collection_name=name)
            params = info.config.params
            vs = params.vectors if params else None
            _VECTOR_SIZE_CACHE[name] = _vector_size_from_collection_config(vs)
        return name
    vector_size = _infer_vector_size(chunks, embeddings)
    return _ensure_collection(folder_id, vector_size)


def get_collection_for_folder(folder_id: str | int) -> str:
    """Legacy helper name. Returns collection name."""
    return _collection_name(folder_id)


def delete_collection_for_folder(folder_id: str | int) -> None:
    """Delete the collection for a folder/project."""
    client = get_qdrant_client()
    name = _collection_name(folder_id)
    try:
        client.delete_collection(collection_name=name)
    except Exception:
        pass


def get_collection_count(folder_id: str | int) -> int:
    """Return number of vectors in the collection for this folder/project."""
    try:
        client = get_qdrant_client()
        name = _collection_name(folder_id)
        if not client.collection_exists(name):
            return 0
        info = client.get_collection(collection_name=name)
        return int(getattr(info, "points_count", 0) or 0)
    except Exception:
        return 0


def add_document_chunks(
    project_id: str,
    document_id: str,
    chunks: list[str],
    filename: str = "",
    embeddings: list[list[float]] | None = None,
    chunk_metadatas: list[dict] | None = None,
    payload_metadata: dict | None = None,
) -> int:
    """
    Add document chunks to Qdrant for the project's collection.
    If embeddings is provided, uses them instead of computing via embedding function.
    Returns number of chunks added.
    """
    if not chunks:
        return 0

    client = get_qdrant_client()
    collection = _ensure_collection_for_upsert(project_id, chunks, embeddings)
    vectors = embeddings if embeddings and len(embeddings) == len(chunks) else [get_embedding(c) for c in chunks]

    points: list[PointStruct] = []
    base_payload = payload_metadata or {}
    for i, chunk in enumerate(chunks):
        chunk_meta = (
            chunk_metadatas[i]
            if chunk_metadatas and i < len(chunk_metadatas) and isinstance(chunk_metadatas[i], dict)
            else {}
        )
        sparse_terms = _sparse_terms(chunk)

        def _page_int(val: object) -> int:
            if val is None:
                return 0
            try:
                n = int(val)
                return n if n > 0 else 0
            except (TypeError, ValueError):
                return 0

        points.append(
            PointStruct(
                id=_point_id(str(document_id), i),
                vector={"dense": [float(x) for x in vectors[i]]},
                payload={
                    "document_id": str(document_id),
                    "project_id": str(project_id),
                    "tenant_id": str(base_payload.get("tenant_id") or project_id),
                    "chunk_index": int(i),
                    "filename": filename or "",
                    "document": chunk,
                    "section": str(chunk_meta.get("section") or ""),
                    "breadcrumb": str(chunk_meta.get("breadcrumb") or ""),
                    "word_start": int(chunk_meta.get("word_start") or 0),
                    "word_end": int(chunk_meta.get("word_end") or 0),
                    "page_start": _page_int(chunk_meta.get("page_start")),
                    "page_end": _page_int(chunk_meta.get("page_end")),
                    "doc_type": str(base_payload.get("doc_type") or ""),
                    "created_at": str(base_payload.get("created_at") or ""),
                    "tags": list(base_payload.get("tags") or []),
                    "sparse_terms": sparse_terms,
                },
            )
        )
    try:
        client.upsert(collection_name=collection, points=points, wait=True)
    except Exception:
        # Backward-compatible fallback for collections created with a single unnamed vector.
        fallback_points: list[PointStruct] = []
        for i, chunk in enumerate(chunks):
            chunk_meta = (
                chunk_metadatas[i]
                if chunk_metadatas and i < len(chunk_metadatas) and isinstance(chunk_metadatas[i], dict)
                else {}
            )

            def _page_int_fb(val: object) -> int:
                if val is None:
                    return 0
                try:
                    n = int(val)
                    return n if n > 0 else 0
                except (TypeError, ValueError):
                    return 0

            fallback_points.append(
                PointStruct(
                    id=_point_id(str(document_id), i),
                    vector=[float(x) for x in vectors[i]],
                    payload={
                        "document_id": str(document_id),
                        "project_id": str(project_id),
                        "tenant_id": str(base_payload.get("tenant_id") or project_id),
                        "chunk_index": int(i),
                        "filename": filename or "",
                        "document": chunk,
                        "section": str(chunk_meta.get("section") or ""),
                        "breadcrumb": str(chunk_meta.get("breadcrumb") or ""),
                        "word_start": int(chunk_meta.get("word_start") or 0),
                        "word_end": int(chunk_meta.get("word_end") or 0),
                        "page_start": _page_int_fb(chunk_meta.get("page_start")),
                        "page_end": _page_int_fb(chunk_meta.get("page_end")),
                        "doc_type": str(base_payload.get("doc_type") or ""),
                        "created_at": str(base_payload.get("created_at") or ""),
                        "tags": list(base_payload.get("tags") or []),
                        "sparse_terms": _sparse_terms(chunk),
                    },
                )
            )
        client.upsert(collection_name=collection, points=fallback_points, wait=True)
    return len(chunks)


def delete_document_chunks(project_id: str, document_id: str) -> None:
    """Remove all chunks for a document from Qdrant."""
    client = get_qdrant_client()
    collection = _collection_name(project_id)
    try:
        if not client.collection_exists(collection):
            return
        filt = Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=str(document_id)),
                )
            ]
        )
        client.delete(collection_name=collection, points_selector=filt, wait=True)
    except Exception:
        pass


def clear_collection_for_folder(folder_id: str | int) -> int:
    """
    Remove all vectors in the collection for this folder/project.
    Returns number of ids deleted. Use before full re-sync.
    """
    client = get_qdrant_client()
    name = _collection_name(folder_id)
    try:
        if not client.collection_exists(name):
            return 0
        count = get_collection_count(folder_id)
        client.delete_collection(collection_name=name)
        _VECTOR_SIZE_CACHE.pop(name, None)
        return count
    except Exception:
        return 0


def sync_project_chunks_to_qdrant(
    project_id: str,
    documents_with_chunks: list[tuple[str, str, str | None, str | None]],
) -> tuple[int, int]:
    """
    Fetch all document embeddings from DB and push to Qdrant.
    documents_with_chunks: list of (document_id, filename, content_json, embeddings_json)
    as stored by upload. Clears the project collection then adds every chunk with its
    stored embedding — no re-embedding; uses the same vectors saved at upload time.
    Returns (documents_synced, chunks_synced).
    """
    clear_collection_for_folder(project_id)
    docs_synced = 0
    chunks_synced = 0
    for document_id, filename, content_json, embeddings_json in documents_with_chunks:
        if not content_json:
            continue
        try:
            content_list = json.loads(content_json) if isinstance(content_json, str) else content_json
        except (TypeError, ValueError):
            continue
        if not isinstance(content_list, list) or not content_list:
            continue
        chunks = [x if isinstance(x, str) else str(x) for x in content_list]
        embeddings: list[list[float]] | None = None
        if embeddings_json:
            try:
                raw = json.loads(embeddings_json) if isinstance(embeddings_json, str) else embeddings_json
                if isinstance(raw, list) and len(raw) == len(chunks):
                    embeddings = [_ensure_float_list(e) for e in raw]
            except (TypeError, ValueError):
                pass
        try:
            n = add_document_chunks(
                project_id, document_id, chunks, filename or "", embeddings=embeddings
            )
            docs_synced += 1
            chunks_synced += n
        except Exception:
            pass
    return docs_synced, chunks_synced


def sync_project_chunks_to_chroma(
    project_id: str,
    documents_with_chunks: list[tuple[str, str, str | None, str | None]],
) -> tuple[int, int]:
    """Alias for older call sites."""
    return sync_project_chunks_to_qdrant(project_id, documents_with_chunks)


def _ensure_float_list(e: list | object) -> list[float]:
    """Ensure one embedding from DB is a list of floats."""
    if isinstance(e, list):
        return [float(x) for x in e]
    return []


def _nearest_search_rows(
    client,
    collection: str,
    query_embedding: list[float],
    limit: int,
    document_ids: list[str] | None = None,
    query_text: str | None = None,
    payload_filters: dict | None = None,
) -> tuple[list[str], list[str], list[dict], list[float]]:
    """Run dual-branch hybrid retrieval (dense+sparse) and fuse with RRF."""
    must_conditions = []
    should_conditions = []
    normalized_doc_ids = [str(x) for x in (document_ids or []) if str(x).strip()]
    if normalized_doc_ids:
        if len(normalized_doc_ids) == 1:
            must_conditions.append(
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=normalized_doc_ids[0]),
                )
            )
        else:
            should_conditions.extend(
                [
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=doc_id),
                    )
                    for doc_id in normalized_doc_ids
                ]
            )
    if isinstance(payload_filters, dict):
        filterable_keys = ("tenant_id", "project_id", "doc_type", "section", "document_id", "filename")
        for key in filterable_keys:
            raw_val = payload_filters.get(key)
            if raw_val is None or raw_val == "":
                continue
            if isinstance(raw_val, list):
                vals = [str(v).strip() for v in raw_val if str(v).strip()]
                should_conditions.extend(
                    [FieldCondition(key=key, match=MatchValue(value=v)) for v in vals]
                )
            else:
                must_conditions.append(FieldCondition(key=key, match=MatchValue(value=str(raw_val))))
        tags_val = payload_filters.get("tags")
        if isinstance(tags_val, list):
            for tag in tags_val:
                s = str(tag).strip()
                if s:
                    must_conditions.append(FieldCondition(key="tags", match=MatchValue(value=s)))
        elif isinstance(tags_val, str) and tags_val.strip():
            must_conditions.append(FieldCondition(key="tags", match=MatchValue(value=tags_val.strip())))
    query_filter = (
        Filter(must=must_conditions, should=should_conditions) if (must_conditions or should_conditions) else None
    )
    branch_limit = max(int(limit), 1) * _BRANCH_EXPANSION
    dense_query = {"name": "dense", "vector": [float(x) for x in query_embedding]}
    try:
        dense_resp = client.query_points(
            collection_name=collection,
            query=dense_query,
            limit=branch_limit,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=False,
        )
    except Exception:
        # Backward-compatible query format when collection stores a single unnamed vector.
        dense_resp = client.query_points(
            collection_name=collection,
            query=[float(x) for x in query_embedding],
            limit=branch_limit,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=False,
        )
    query_sparse = _sparse_query_map(query_text or "")
    dense_rank: dict[str, int] = {}
    dense_score_by_id: dict[str, float] = {}
    point_by_id: dict[str, object] = {}
    for idx, p in enumerate(dense_resp.points or []):
        pid = str(p.id)
        dense_rank[pid] = idx + 1
        dense_score_by_id[pid] = max(0.0, min(1.0, float(p.score or 0.0)))
        point_by_id[pid] = p

    sparse_rank: dict[str, int] = {}
    sparse_score_by_id: dict[str, float] = {}
    if query_sparse:
        scanned = 0
        offset = None
        scored_sparse: list[tuple[float, str, object]] = []
        while scanned < _SPARSE_SCAN_CAP:
            page_size = min(100, _SPARSE_SCAN_CAP - scanned)
            points, next_offset = client.scroll(
                collection_name=collection,
                scroll_filter=query_filter,
                offset=offset,
                limit=page_size,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break
            for p in points:
                scanned += 1
                pid = str(p.id)
                payload = p.payload or {}
                sparse_score = _sparse_overlap_score(query_sparse, payload.get("sparse_terms") or [])
                if sparse_score > 0.0:
                    scored_sparse.append((sparse_score, pid, p))
                    point_by_id.setdefault(pid, p)
                if scanned >= _SPARSE_SCAN_CAP:
                    break
            if not next_offset or scanned >= _SPARSE_SCAN_CAP:
                break
            offset = next_offset
        scored_sparse.sort(key=lambda x: x[0], reverse=True)
        for idx, (score, pid, _) in enumerate(scored_sparse[:branch_limit]):
            sparse_rank[pid] = idx + 1
            sparse_score_by_id[pid] = score

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []
    distances: list[float] = []
    fused_rows: list[tuple[float, str, str, dict, float]] = []
    fused_ids = set(dense_rank.keys()) | set(sparse_rank.keys())
    if not fused_ids:
        return ids, documents, metadatas, distances
    rrf_scores: dict[str, float] = {}
    for pid in fused_ids:
        score = 0.0
        if pid in dense_rank:
            score += 1.0 / (_RRF_K + dense_rank[pid])
        if pid in sparse_rank:
            score += 1.0 / (_RRF_K + sparse_rank[pid])
        rrf_scores[pid] = score
    max_rrf = max(rrf_scores.values()) if rrf_scores else 1.0
    for pid in sorted(fused_ids, key=lambda x: rrf_scores.get(x, 0.0), reverse=True):
        h = point_by_id.get(pid)
        payload = (h.payload if h else {}) or {}
        dense_sim = dense_score_by_id.get(pid, 0.0)
        sparse_sim = sparse_score_by_id.get(pid, 0.0)
        rrf_norm = (rrf_scores.get(pid, 0.0) / max_rrf) if max_rrf > 0 else 0.0
        pseudo_distance = max(0.0, 1.0 - rrf_norm)
        ps = int(payload.get("page_start") or 0)
        pe = int(payload.get("page_end") or 0)
        row_meta = {
            "document_id": str(payload.get("document_id") or ""),
            "chunk_index": int(payload.get("chunk_index") or 0),
            "filename": str(payload.get("filename") or ""),
            "section": str(payload.get("section") or ""),
            "breadcrumb": str(payload.get("breadcrumb") or ""),
            "word_start": int(payload.get("word_start") or 0),
            "word_end": int(payload.get("word_end") or 0),
            "page_start": ps if ps > 0 else None,
            "page_end": pe if pe > 0 else None,
            "tenant_id": str(payload.get("tenant_id") or ""),
            "project_id": str(payload.get("project_id") or ""),
            "doc_type": str(payload.get("doc_type") or ""),
            "created_at": str(payload.get("created_at") or ""),
            "tags": list(payload.get("tags") or []),
            "dense_score": round(dense_sim, 6),
            "sparse_score": round(sparse_sim, 6),
            "hybrid_score": round(rrf_norm, 6),
        }
        fused_rows.append((rrf_norm, pid, str(payload.get("document") or ""), row_meta, pseudo_distance))
    for _, pid, doc_text, md, dist in fused_rows[: max(1, int(limit))]:
        ids.append(pid)
        documents.append(doc_text)
        metadatas.append(md)
        distances.append(dist)
    return ids, documents, metadatas, distances


def query_collection(
    project_id: str,
    query_embedding: list[float],
    n_results: int = 5,
    include: list[str] | None = None,
    document_ids: list[str] | None = None,
    query_text: str | None = None,
    payload_filters: dict | None = None,
) -> dict:
    """
    Search collection using a query embedding.
    Returns shape compatible with old Chroma callers: ids/documents/metadatas/distances,
    each a list containing one inner list (one query).
    """
    _ = include
    client = get_qdrant_client()
    collection = _collection_name(project_id)
    if not client.collection_exists(collection):
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    ids, documents, metadatas, distances = _nearest_search_rows(
        client,
        collection,
        query_embedding,
        n_results,
        document_ids=document_ids,
        query_text=query_text,
        payload_filters=payload_filters,
    )
    return {"ids": [ids], "documents": [documents], "metadatas": [metadatas], "distances": [distances]}


def query_collection_multi(
    project_id: str,
    query_embeddings: list[list[float]],
    query_texts: list[str] | None = None,
    n_results_per_query: int = 15,
    total_results: int = 25,
    include: list[str] | None = None,
    document_ids: list[str] | None = None,
    payload_filters: dict | None = None,
) -> dict:
    """
    Search with multiple query embeddings.
    Merges results using Reciprocal Rank Fusion (RRF) and returns top total_results.
    """
    if not query_embeddings:
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    _ = include
    client = get_qdrant_client()
    collection = _collection_name(project_id)
    if not client.collection_exists(collection):
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    ids_list: list[list[str]] = []
    documents_list: list[list[str]] = []
    metadatas_list: list[list[dict]] = []
    distances_list: list[list[float]] = []

    for idx, emb in enumerate(query_embeddings):
        q_text = query_texts[idx] if query_texts and idx < len(query_texts) else None
        row_ids, row_docs, row_metas, row_dists = _nearest_search_rows(
            client,
            collection,
            emb,
            n_results_per_query,
            document_ids=document_ids,
            query_text=q_text,
            payload_filters=payload_filters,
        )
        ids_list.append(row_ids)
        documents_list.append(row_docs)
        metadatas_list.append(row_metas)
        distances_list.append(row_dists)

    # RRF: score(d) = sum over rankings of 1/(k + rank(d)), k=60
    k_rrf = 60
    rrf_scores: dict[str, float] = {}
    id_to_data: dict[str, tuple[str, dict, float]] = {}

    for rank_idx, ids in enumerate(ids_list):
        docs = documents_list[rank_idx] if rank_idx < len(documents_list) else []
        metas = metadatas_list[rank_idx] if rank_idx < len(metadatas_list) else []
        dists = distances_list[rank_idx] if rank_idx < len(distances_list) else []

        for r, chunk_id in enumerate(ids):
            if chunk_id not in rrf_scores:
                rrf_scores[chunk_id] = 0.0
                doc = docs[r] if r < len(docs) else ""
                meta = metas[r] if r < len(metas) else {}
                dist = float(dists[r]) if r < len(dists) else 0.0
                id_to_data[chunk_id] = (doc, meta, dist)
            rrf_scores[chunk_id] += 1.0 / (k_rrf + r)

    sorted_ids = sorted(
        rrf_scores.keys(),
        key=lambda x: rrf_scores[x],
        reverse=True,
    )[:total_results]

    out_ids = []
    out_docs = []
    out_metas = []
    out_dists = []

    for cid in sorted_ids:
        doc, meta, dist = id_to_data.get(cid, ("", {}, 0.0))
        out_ids.append(cid)
        out_docs.append(doc)
        out_metas.append(meta)
        out_dists.append(dist)

    return {
        "ids": [out_ids],
        "documents": [out_docs],
        "metadatas": [out_metas],
        "distances": [out_dists],
    }
