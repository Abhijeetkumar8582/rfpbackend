"""Documents API — upload (chunk → embed → categorize → ChromaDB → S3), list, get, download, delete."""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.core.document_id import generate_document_id
from app.config import settings
from app.database import SessionLocal
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.project import Project
from app.models.user import User
from app.schemas.document import (
    DocumentResponse,
    DocumentUpdate,
    DocumentChunksResponse,
    DocumentChunkItem,
    DocumentMetadataResponse,
)
from app.schemas.common import IDResponse, Message
from app.services.text_extract import extract_text_from_file
from app.services.chunking import chunk_text_by_words
from app.services.embeddings import get_embedding, embedding_to_json
from app.services.categorize import categorize_document
from app.services.doc_metadata import generate_doc_metadata
from app.services.s3 import s3_upload, build_s3_key, s3_download
from app.services.chroma import add_document_chunks, delete_document_chunks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


def _embed_and_categorize(text: str, filename: str) -> tuple[str | None, str]:
    """Return (embedding_json, cluster). Uses 'Uncategorized' if OpenAI unavailable."""
    cluster = "Uncategorized"
    embedding_json = None
    if settings.openai_api_key:
        try:
            embedding = get_embedding(text[:8_000])
            embedding_json = embedding_to_json(embedding)
            cluster = categorize_document(text, filename)
        except Exception as e:
            logger.warning("OpenAI embed/categorize failed: %s", e)
    return embedding_json, cluster


def _upload_to_s3(body: bytes, project_id: str, cluster: str, filename: str, content_type: str) -> str | None:
    """Upload to S3. Returns s3_key or None if S3 unavailable."""
    if not settings.s3_bucket:
        logger.warning("S3 upload skipped: S3_BUCKET not set in .env")
        return None
    try:
        s3_key = build_s3_key(project_id, cluster, filename)
        s3_upload(body, s3_key, content_type)
        logger.info("S3 upload succeeded: key=%s", s3_key)
        return s3_key
    except Exception as e:
        logger.warning("S3 upload failed: %s", e)
        return None


@router.get("", response_model=list[DocumentResponse])
def list_documents(db: DbSession, project_id: str | None = None, skip: int = 0, limit: int = 100):
    """List documents, optionally by project. TODO: add auth, filter by access."""
    q = select(Document).where(Document.deleted_at.is_(None))
    if project_id is not None:
        q = q.where(Document.project_id == project_id)
    q = q.offset(skip).limit(limit).order_by(Document.uploaded_at.desc())
    return list(db.execute(q).scalars().all())


def _run_generate_metadata_background(document_id: str) -> None:
    """Background task: load doc + chunks, generate metadata via GPT, update document and document_chunks."""
    db = SessionLocal()
    try:
        doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
        if not doc or doc.deleted_at:
            return
        chunk_row = db.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).scalars().one_or_none()
        if not chunk_row or not chunk_row.content:
            return
        content_list = json.loads(chunk_row.content) if isinstance(chunk_row.content, str) else chunk_row.content
        if not isinstance(content_list, list) or not content_list:
            return
        chunks = [x if isinstance(x, str) else str(x) for x in content_list]
        meta = generate_doc_metadata(document_id, doc.filename, chunks)
        title = meta.get("title")
        desc = meta.get("description")
        doc_type = meta.get("doc_type")
        tags_str = json.dumps(meta.get("tags", []))
        taxonomy_str = json.dumps(meta.get("taxonomy_suggestions", {}))
        doc.doc_title = title
        doc.doc_description = desc
        doc.doc_type = doc_type
        doc.tags_json = tags_str
        doc.taxonomy_suggestions_json = taxonomy_str
        chunk_row.doc_title = title
        chunk_row.doc_description = desc
        chunk_row.doc_type = doc_type
        chunk_row.tags_json = tags_str
        chunk_row.taxonomy_suggestions_json = taxonomy_str
        db.commit()
        logger.info("Document metadata generated: document_id=%s title=%s", document_id, title)
    except Exception as e:
        logger.warning("Background metadata generation failed for document_id=%s: %s", document_id, e)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


@router.post("", response_model=IDResponse)
async def upload_document(
    db: DbSession,
    background_tasks: BackgroundTasks,
    project_id: str = Form(...),
    uploaded_by: str = Form(..., description="User ID (UUID) who is uploading"),
    file: UploadFile = File(...),
):
    """
    Upload: extract text → chunk → embed → categorize → ChromaDB → S3.
    Resilient: document is created even if OpenAI, S3, or ChromaDB fail.
    """
    logger.info("Document upload request received: filename=%s project_id=%s", file.filename, project_id)
    filename = file.filename or "document"
    content_type = file.content_type or "application/octet-stream"
    body = await file.read()
    size_bytes = len(body)

    project = db.execute(select(Project).where(Project.id == project_id)).scalars().one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    user = db.execute(select(User).where(User.id == uploaded_by)).scalars().one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found (invalid uploaded_by)")

    doc = Document(
        id=generate_document_id(db),
        project_id=project_id,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        storage_path="pending",
        status=DocumentStatus.ingesting,
        uploaded_by=uploaded_by,
        uploaded_at=datetime.now(timezone.utc),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    try:
        text = extract_text_from_file(body, filename, content_type)
        if not text or not text.strip():
            text = f"Filename: {filename}"

        # Embedding + categorization (resilient)
        embedding_json, cluster = _embed_and_categorize(text, filename)
        doc.embedding_json = embedding_json
        doc.cluster = cluster
        db.commit()

        # Chunk by words (e.g. 200 words per chunk), embed, persist to DB, and add to ChromaDB
        chunks = chunk_text_by_words(
            text,
            words_per_chunk=settings.chunk_size_words,
            overlap_words=settings.chunk_overlap_words,
        )
        if chunks:
            chunk_embeddings: list[list[float]] | None = None
            if settings.openai_api_key:
                try:
                    chunk_embeddings = [get_embedding(c) for c in chunks]
                except Exception as e:
                    logger.warning("Chunk embedding failed: %s", e)
            content_json = json.dumps(chunks)
            embeddings_json = json.dumps(chunk_embeddings) if chunk_embeddings and len(chunk_embeddings) == len(chunks) else None
            db.add(DocumentChunk(document_id=doc.id, content=content_json, embeddings_json=embeddings_json, chunk_count=len(chunks)))
            db.commit()
            if settings.openai_api_key and chunk_embeddings and len(chunk_embeddings) == len(chunks):
                try:
                    add_document_chunks(project_id, doc.id, chunks, filename, embeddings=chunk_embeddings)
                except Exception as e:
                    logger.warning("ChromaDB add chunks failed: %s", e)
            elif settings.openai_api_key and not chunk_embeddings:
                try:
                    add_document_chunks(project_id, doc.id, chunks, filename)
                except Exception as e:
                    logger.warning("ChromaDB add chunks failed: %s", e)

        # S3 upload (resilient)
        s3_key = _upload_to_s3(body, project_id, cluster, filename, content_type)
        doc.storage_path = s3_key if s3_key else f"local/{doc.id}/{filename}"
        doc.status = DocumentStatus.ingested
        doc.ingested_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(doc)
        # Generate GPT metadata from chunks (runs in background after response)
        if chunks and settings.openai_api_key:
            background_tasks.add_task(_run_generate_metadata_background, doc.id)
    except ValueError as e:
        doc.status = DocumentStatus.failed
        try:
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except IntegrityError as e:
        doc.status = DocumentStatus.failed
        try:
            db.commit()
        except Exception:
            db.rollback()
        logger.warning("Document upload integrity error: %s", e)
        raise HTTPException(status_code=400, detail="Invalid project or user reference")
    except Exception as e:
        doc.status = DocumentStatus.failed
        try:
            db.commit()
        except Exception:
            db.rollback()
        logger.exception("Document upload failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Processing failed: {e!s}")

    return IDResponse(id=doc.id)


@router.get("/{document_id}/chunks", response_model=DocumentChunksResponse)
def get_document_chunks(document_id: str, db: DbSession):
    """Get vector chunks for a document from document_chunks table. Supports both schemas: one row with JSON array or multiple rows with chunk_index+content."""
    doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.deleted_at:
        raise HTTPException(status_code=404, detail="Document deleted")

    chunks_out: list[DocumentChunkItem] = []

    # 1) Try one row per document: content column = JSON array of strings
    try:
        result = db.execute(
            text("SELECT content FROM document_chunks WHERE document_id = :doc_id LIMIT 1"),
            {"doc_id": document_id},
        )
        row = result.mappings().first()
        if row and row.get("content"):
            raw = row["content"]
            content_list = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(content_list, list):
                for i, item in enumerate(content_list):
                    content = item if isinstance(item, str) else str(item)
                    chunks_out.append(
                        DocumentChunkItem(index=i + 1, content=content, tokens=max(1, len(content) // 4))
                    )
                return DocumentChunksResponse(chunks=chunks_out, chunk_count=len(chunks_out))
    except (TypeError, json.JSONDecodeError, Exception):
        pass

    # 2) Fallback: multiple rows per document (chunk_index, content)
    try:
        result = db.execute(
            text(
                "SELECT chunk_index, content FROM document_chunks WHERE document_id = :doc_id ORDER BY chunk_index"
            ),
            {"doc_id": document_id},
        )
        rows = result.mappings().all()
        for r in rows:
            idx = int(r.get("chunk_index", 0)) or (len(chunks_out) + 1)
            content = (r.get("content") or "").strip() or ""
            chunks_out.append(
                DocumentChunkItem(index=idx, content=content, tokens=max(1, len(content) // 4))
            )
        if chunks_out:
            # Normalize indices to 1-based consecutive
            for i, c in enumerate(chunks_out):
                chunks_out[i] = DocumentChunkItem(index=i + 1, content=c.content, tokens=c.tokens)
            return DocumentChunksResponse(chunks=chunks_out, chunk_count=len(chunks_out))
    except Exception:
        pass

    return DocumentChunksResponse(chunks=[], chunk_count=0)


@router.post("/{document_id}/generate-metadata", response_model=DocumentMetadataResponse)
def generate_document_metadata(document_id: str, db: DbSession):
    """Generate GPT metadata from document chunks (title, description, doc_type, tags, taxonomy). Runs once chunks exist."""
    doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.deleted_at:
        raise HTTPException(status_code=404, detail="Document deleted")
    chunk_row = db.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    ).scalars().one_or_none()
    if not chunk_row or not chunk_row.content:
        raise HTTPException(status_code=400, detail="No chunks found; run upload/chunking first")
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")
    content_list = json.loads(chunk_row.content) if isinstance(chunk_row.content, str) else chunk_row.content
    if not isinstance(content_list, list) or not content_list:
        raise HTTPException(status_code=400, detail="No chunks in document")
    chunks = [x if isinstance(x, str) else str(x) for x in content_list]
    try:
        meta = generate_doc_metadata(document_id, doc.filename, chunks)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    title = meta.get("title")
    desc = meta.get("description")
    doc_type = meta.get("doc_type")
    tags_str = json.dumps(meta.get("tags", []))
    taxonomy_str = json.dumps(meta.get("taxonomy_suggestions", {}))
    doc.doc_title = title
    doc.doc_description = desc
    doc.doc_type = doc_type
    doc.tags_json = tags_str
    doc.taxonomy_suggestions_json = taxonomy_str
    chunk_row.doc_title = title
    chunk_row.doc_description = desc
    chunk_row.doc_type = doc_type
    chunk_row.tags_json = tags_str
    chunk_row.taxonomy_suggestions_json = taxonomy_str
    db.commit()
    return DocumentMetadataResponse(
        document_id=document_id,
        title=meta.get("title", ""),
        description=meta.get("description", ""),
        doc_type=meta.get("doc_type", "other"),
        tags=meta.get("tags", []),
        taxonomy_suggestions=meta.get("taxonomy_suggestions", {}),
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, db: DbSession):
    """Get document metadata. TODO: check project access."""
    doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.patch("/{document_id}", response_model=DocumentResponse)
def update_document(document_id: str, body: DocumentUpdate, db: DbSession):
    """Update document metadata (title, description, doc_type, tags, taxonomy). Soft-deleted docs return 404."""
    doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.deleted_at:
        raise HTTPException(status_code=404, detail="Document deleted")

    if body.doc_title is not None:
        doc.doc_title = body.doc_title
    if body.doc_description is not None:
        doc.doc_description = body.doc_description
    if body.doc_type is not None:
        doc.doc_type = body.doc_type
    if body.tags is not None:
        doc.tags_json = json.dumps(body.tags)
    if body.taxonomy_suggestions is not None:
        doc.taxonomy_suggestions_json = json.dumps(body.taxonomy_suggestions)

    # Keep document_chunks in sync (one row per document)
    chunk_row = db.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    ).scalars().one_or_none()
    if chunk_row:
        if body.doc_title is not None:
            chunk_row.doc_title = body.doc_title
        if body.doc_description is not None:
            chunk_row.doc_description = body.doc_description
        if body.doc_type is not None:
            chunk_row.doc_type = body.doc_type
        if body.tags is not None:
            chunk_row.tags_json = doc.tags_json
        if body.taxonomy_suggestions is not None:
            chunk_row.taxonomy_suggestions_json = doc.taxonomy_suggestions_json

    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{document_id}/download")
def download_document(document_id: str, db: DbSession):
    """Download file from S3 or return 404 if stored locally."""
    doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.deleted_at:
        raise HTTPException(status_code=404, detail="Document deleted")

    storage_path = doc.storage_path or ""
    if storage_path.startswith("local/"):
        raise HTTPException(status_code=404, detail="File stored locally; download not available")

    try:
        url = s3_download(storage_path, doc.content_type)
        return RedirectResponse(url=url, status_code=302)
    except Exception as e:
        logger.warning("S3 presigned URL failed: %s", e)
        raise HTTPException(status_code=503, detail="Download unavailable")


@router.delete("/{document_id}", response_model=Message)
def delete_document(document_id: str, db: DbSession):
    """Soft-delete document and remove chunks from ChromaDB."""
    doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.deleted_at:
        return Message(message="Already deleted")

    doc.deleted_at = datetime.now(timezone.utc)
    doc.status = DocumentStatus.deleted
    # Remove chunks from DB (cascade would work on hard delete; we explicit-delete for soft delete)
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    db.commit()

    try:
        delete_document_chunks(doc.project_id, doc.id)
    except Exception as e:
        logger.warning("ChromaDB delete chunks failed: %s", e)

    return Message(message="Deleted")
