"""Services — S3, text extraction, embeddings, categorization."""
from app.services.s3 import s3_upload
from app.services.text_extract import extract_text_from_file
from app.services.embeddings import get_embedding
from app.services.categorize import categorize_document

__all__ = [
    "s3_upload",
    "extract_text_from_file",
    "get_embedding",
    "categorize_document",
]
