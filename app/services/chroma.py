"""ChromaDB — single client instance with one collection per folder (project)."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app.config import settings
from app.services.embeddings import get_embedding

if TYPE_CHECKING:
    import chromadb
    from chromadb.api.models.Collection import Collection

# ---------------------------------------------------------------------------
# Single (parent) ChromaDB client instance
# ---------------------------------------------------------------------------

_chroma_client: "chromadb.PersistentClient | None" = None


def get_chroma_client() -> "chromadb.PersistentClient":
    """Return the single shared ChromaDB client (parent instance)."""
    global _chroma_client
    if _chroma_client is None:
        import chromadb

        _chroma_client = chromadb.PersistentClient(path=settings.chroma_persist_path)
    return _chroma_client


# ---------------------------------------------------------------------------
# Embedding function for ChromaDB (list of texts -> list of vectors)
# ---------------------------------------------------------------------------


class _OpenAIEmbeddingFn:
    """ChromaDB embedding function using app OpenAI embeddings."""

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [get_embedding(t) for t in input]

    def name(self) -> str:
        return "openai_app"


_embedding_fn = _OpenAIEmbeddingFn()


# ---------------------------------------------------------------------------
# Child instance per folder = one collection per folder
# ---------------------------------------------------------------------------


def get_collection_for_folder(folder_id: str | int) -> "Collection":
    """
    Get or create the ChromaDB collection for the given folder (inner child instance).
    Use project_id or any folder identifier as folder_id.
    """
    client = get_chroma_client()
    name = _collection_name(folder_id)
    return client.get_or_create_collection(
        name=name,
        metadata={"folder_id": str(folder_id)},
        embedding_function=_embedding_fn,
    )


def _collection_name(folder_id: str | int) -> str:
    """Stable collection name for a folder (safe for ChromaDB)."""
    return f"folder_{folder_id}"


def delete_collection_for_folder(folder_id: str | int) -> None:
    """Delete the collection for a folder (e.g. when project/folder is removed)."""
    client = get_chroma_client()
    name = _collection_name(folder_id)
    try:
        client.delete_collection(name=name)
    except Exception:
        pass  # no-op if collection does not exist


def add_document_chunks(
    project_id: int,
    document_id: int,
    chunks: list[str],
    filename: str = "",
    embeddings: list[list[float]] | None = None,
) -> int:
    """
    Add document chunks to ChromaDB for the project's collection.
    If embeddings is provided, uses them instead of computing via embedding function.
    Returns number of chunks added.
    """
    if not chunks:
        return 0
    coll = get_collection_for_folder(project_id)
    ids = [f"doc_{document_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [
        {"document_id": document_id, "chunk_index": i, "filename": filename}
        for i in range(len(chunks))
    ]
    if embeddings and len(embeddings) == len(chunks):
        coll.add(documents=chunks, embeddings=embeddings, metadatas=metadatas, ids=ids)
    else:
        coll.add(documents=chunks, metadatas=metadatas, ids=ids)
    return len(chunks)


def delete_document_chunks(project_id: int, document_id: int) -> None:
    """Remove all chunks for a document from ChromaDB."""
    coll = get_collection_for_folder(project_id)
    try:
        result = coll.get(where={"document_id": {"$eq": document_id}})
        if result and result.get("ids"):
            coll.delete(ids=result["ids"])
    except Exception:
        pass


def clear_collection_for_folder(folder_id: str | int) -> int:
    """
    Remove all vectors in the collection for this folder (project).
    Returns number of ids deleted. Use before full re-sync to ChromaDB.
    """
    coll = get_collection_for_folder(folder_id)
    try:
        result = coll.get(include=[])
        ids = result.get("ids") if result else []
        if ids:
            coll.delete(ids=ids)
        return len(ids)
    except Exception:
        return 0


def sync_project_chunks_to_chroma(
    project_id: int,
    documents_with_chunks: list[tuple[int, str, str | None, str | None]],
) -> tuple[int, int]:
    """
    Fetch all document embeddings from DB and push to ChromaDB (vector store).
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
        # Use stored embeddings from DB (saved when file was uploaded); no re-embedding
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


def _ensure_float_list(e: list | object) -> list[float]:
    """Ensure one embedding from DB is a list of floats for ChromaDB."""
    if isinstance(e, list):
        return [float(x) for x in e]
    return []


def query_collection(
    project_id: int,
    query_embedding: list[float],
    n_results: int = 5,
    include: list[str] | None = None,
) -> dict:
    """
    Search ChromaDB using a query embedding (e.g. from the user's question).
    Returns the top-n_results closest chunks by vector similarity.
    include: optional list of what to return (default: ["documents", "metadatas", "distances"]).
    """
    if include is None:
        include = ["documents", "metadatas", "distances"]
    coll = get_collection_for_folder(project_id)
    result = coll.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=include,
    )
    return result
