"""Services — S3, text extraction, embeddings, categorization, Qdrant."""
from app.services.s3 import s3_upload
from app.services.text_extract import extract_text_from_file
from app.services.embeddings import get_embedding
from app.services.categorize import categorize_document
from app.services.qdrant import (
    get_qdrant_client,
    get_collection_for_folder,
    delete_collection_for_folder,
)

__all__ = [
    "s3_upload",
    "extract_text_from_file",
    "get_embedding",
    "categorize_document",
    "get_qdrant_client",
    "get_collection_for_folder",
    "delete_collection_for_folder",
]
