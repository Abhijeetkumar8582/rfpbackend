"""Deprecated: implementation moved to `app.services.qdrant`. Import from there."""

from app.services.qdrant import (  # noqa: F401
    add_document_chunks,
    clear_collection_for_folder,
    delete_collection_for_folder,
    delete_document_chunks,
    get_chroma_client,
    get_collection_count,
    get_collection_for_folder,
    get_qdrant_client,
    query_collection,
    query_collection_multi,
    sync_project_chunks_to_chroma,
    sync_project_chunks_to_qdrant,
)
