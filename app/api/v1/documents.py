"""Documents API — upload (chunk → embed → categorize → Qdrant → S3), list, get, download, delete."""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, CurrentUser, CurrentUserOptional, require_admin_or_manager
from app.core.project_access import get_accessible_project_ids, require_document_access, require_project_access
from app.models.user import UserRole
from app.core.document_id import generate_document_id
from app.config import settings
from app.database import SessionLocal
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.project import Project
from app.models.user import User

def _require_can_modify_document(current_user: User | None, doc: Document) -> None:
    """Allow Super Admin, Admin, or the document uploader. Raise 401/403 otherwise."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if current_user.role in (UserRole.admin, UserRole.manager):
        return
    if doc.uploaded_by and doc.uploaded_by == current_user.id:
        return
    raise HTTPException(
        status_code=403,
        detail="Only Super Admin, Admin, or the document uploader can modify or delete this document.",
    )
from app.schemas.document import (
    DocumentResponse,
    DocumentUpdate,
    DocumentChunksResponse,
    DocumentChunkItem,
    DocumentMetadataResponse,
    PdfExtractImagesResponse,
)
from app.schemas.common import IDResponse, Message
from app.services.text_extract import extract_text_from_file, extract_pdf_with_page_map
from app.services.chunking import chunk_text_by_sections
from app.services.embeddings import get_embedding, embedding_to_json, is_embedding_configured
from app.services.categorize import categorize_document
from app.services.doc_metadata import generate_doc_metadata
from app.services.s3 import s3_upload, build_s3_key, s3_download, build_s3_object_url
from app.services.qdrant import add_document_chunks, delete_document_chunks
from app.services.pdf_ocr import is_probably_scanned, extract_images_and_ocr_text

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


def _upload_to_s3(body: bytes, project_id: str, cluster: str, filename: str, content_type: str) -> tuple[str | None, str | None]:
    """Upload to S3. Returns (s3_key, error_message)."""
    if not settings.s3_bucket:
        logger.warning("S3 upload skipped: S3_BUCKET not set in .env")
        return None, "S3 bucket is not configured (S3_BUCKET missing)."
    try:
        s3_key = build_s3_key(project_id, cluster, filename)
        s3_upload(body, s3_key, content_type)
        logger.info("S3 upload succeeded: key=%s", s3_key)
        return s3_key, None
    except Exception as e:
        logger.warning("S3 upload failed: %s", e)
        return None, str(e)


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    db: DbSession,
    current_user: CurrentUser,
    project_id: str | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """List documents the caller may access (project membership or uploader; admins see all)."""
    q = select(Document).where(Document.deleted_at.is_(None))
    accessible = get_accessible_project_ids(db, current_user)
    if accessible is not None:
        if not accessible:
            return []
        if project_id is not None:
            if project_id not in accessible:
                raise HTTPException(status_code=403, detail="Access denied")
            q = q.where(Document.project_id == project_id)
        else:
            q = q.where(Document.project_id.in_(accessible))
    elif project_id is not None:
        q = q.where(Document.project_id == project_id)
    q = q.offset(skip).limit(limit).order_by(Document.uploaded_at.desc())
    return list(db.execute(q).scalars().all())


@router.post("/pdf-extract-images", response_model=PdfExtractImagesResponse)
async def pdf_extract_images(
    current_user: CurrentUser,
    file: UploadFile = File(...),
):
    """
    Scan the whole PDF, extract all images, and convert to text via OCR.
    Use when a PDF appears to be scanned or image-heavy (e.g. after is_probably_scanned).
    """
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty file")

    is_scanned = is_probably_scanned(body)
    extracted_text, pages_processed = extract_images_and_ocr_text(body)

    return PdfExtractImagesResponse(
        extracted_text=extracted_text,
        is_probably_scanned=is_scanned,
        pages_processed=pages_processed,
    )


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
    current_user: CurrentUserOptional,
    project_id: str = Form(...),
    uploaded_by: str = Form(..., description="User ID (UUID) who is uploading"),
    file: UploadFile = File(...),
    extract_pdf_images: str = Form("true", description="If true, extract text from images in PDFs (scanned docs)"),
):
    """
    Upload: extract text → chunk → embed → Qdrant (local or configured URL) → S3.
    Only Super Admin or Admin can upload.
    Resilient for OpenAI/Qdrant; S3 upload is required and returns an error if it fails.
    """
    require_admin_or_manager(current_user)
    logger.info("Document upload request received: filename=%s project_id=%s", file.filename, project_id)
    filename = file.filename or "document"
    content_type = file.content_type or "application/octet-stream"
    body = await file.read()
    size_bytes = len(body)

    project = db.execute(select(Project).where(Project.id == project_id)).scalars().one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    require_project_access(db, current_user, project_id)
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
        run_pdf_ocr = extract_pdf_images.lower() not in ("false", "0", "no", "off")
        is_pdf = ("pdf" in (content_type or "").lower()) or (filename or "").lower().endswith(".pdf")
        page_char_starts: list[int] | None = None
        if is_pdf:
            text, page_char_starts = extract_pdf_with_page_map(body)
            if not text or not text.strip():
                text = extract_text_from_file(body, filename, content_type)
                page_char_starts = None
        else:
            text = extract_text_from_file(body, filename, content_type)

        # For PDFs: OCR image-heavy or text-empty PDFs when extract_pdf_images is enabled.
        ocr_attempted = False
        if run_pdf_ocr and is_pdf:
            ocr_attempted = True
            ocr_text, _ = extract_images_and_ocr_text(body)
            if ocr_text and ocr_text.strip():
                text = (text.strip() + "\n\n" + ocr_text).strip() if text and text.strip() else ocr_text
                page_char_starts = None  # merged OCR breaks page alignment
                logger.info("Merged OCR text from PDF images for document_id=%s", doc.id)

        if run_pdf_ocr and is_pdf and ocr_attempted and not (text and text.strip()):
            logger.warning(
                "OCR attempted but no text extracted for document_id=%s. "
                "Check OCR runtime dependencies (PyMuPDF, pytesseract, Pillow, Tesseract binary).",
                doc.id,
            )

        if not text or not text.strip():
            text = f"Filename: {filename}"

        # Embedding + categorization (resilient)
        embedding_json, cluster = _embed_and_categorize(text, filename)
        doc.embedding_json = embedding_json
        doc.cluster = cluster
        db.commit()

        # Structure-first chunking; old per-project word knobs are mapped to char thresholds.
        chunk_sz = project.chunk_size_words if project.chunk_size_words is not None else settings.chunk_size_words
        overlap_sz = project.chunk_overlap_words if project.chunk_overlap_words is not None else settings.chunk_overlap_words
        max_chunk_chars = max(600, int(chunk_sz) * 6)
        overlap_chars = max(40, int(overlap_sz) * 5)
        section_chunks = chunk_text_by_sections(
            text,
            max_chunk_chars=max_chunk_chars,
            overlap_chars=overlap_chars,
            page_char_starts=page_char_starts,
        )
        chunks = [c.get("text", "") for c in section_chunks if c.get("text")]
        chunk_metadatas = [
            {
                "section": c.get("section"),
                "breadcrumb": c.get("breadcrumb"),
                "word_start": c.get("word_start"),
                "word_end": c.get("word_end"),
                "page_start": c.get("page_start"),
                "page_end": c.get("page_end"),
            }
            for c in section_chunks
            if c.get("text")
        ]
        if chunks:
            chunk_embeddings: list[list[float]] | None = None
            if is_embedding_configured():
                try:
                    chunk_embeddings = [get_embedding(c) for c in chunks]
                except Exception as e:
                    logger.warning("Chunk embedding failed: %s", e)
            content_json = json.dumps(chunks)
            embeddings_json = json.dumps(chunk_embeddings) if chunk_embeddings and len(chunk_embeddings) == len(chunks) else None
            db.add(DocumentChunk(document_id=doc.id, content=content_json, embeddings_json=embeddings_json, chunk_count=len(chunks)))
            db.commit()
            if is_embedding_configured():
                try:
                    if chunk_embeddings and len(chunk_embeddings) == len(chunks):
                        n = add_document_chunks(
                            project_id,
                            doc.id,
                            chunks,
                            filename,
                            embeddings=chunk_embeddings,
                            chunk_metadatas=chunk_metadatas,
                            payload_metadata={
                                "tenant_id": project_id,
                                "project_id": project_id,
                                "doc_type": doc.doc_type or "",
                                "created_at": doc.uploaded_at.isoformat() if doc.uploaded_at else "",
                                "tags": [],
                            },
                        )
                    else:
                        n = add_document_chunks(
                            project_id,
                            doc.id,
                            chunks,
                            filename,
                            chunk_metadatas=chunk_metadatas,
                            payload_metadata={
                                "tenant_id": project_id,
                                "project_id": project_id,
                                "doc_type": doc.doc_type or "",
                                "created_at": doc.uploaded_at.isoformat() if doc.uploaded_at else "",
                                "tags": [],
                            },
                        )
                    logger.info(
                        "Qdrant: stored %s chunk vectors for document_id=%s project_id=%s",
                        n,
                        doc.id,
                        project_id,
                    )
                except Exception as e:
                    logger.exception("Qdrant upsert failed for document_id=%s project_id=%s", doc.id, project_id)
                    raise RuntimeError(
                        "Vector indexing failed, so this document is not searchable yet. "
                        "Please ensure Qdrant is running and retry the upload."
                    ) from e

        # S3 upload (resilient)
        s3_key, s3_error = _upload_to_s3(body, project_id, cluster, filename, content_type)
        if s3_key is None:
            raise RuntimeError(f"S3 upload failed: {s3_error}")
        doc.storage_path = s3_key if s3_key else f"local/{doc.id}/{filename}"
        doc.s3_url = build_s3_object_url(s3_key) if s3_key else None
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
def get_document_chunks(document_id: str, db: DbSession, current_user: CurrentUser):
    """Get vector chunks for a document from document_chunks table. Supports both schemas: one row with JSON array or multiple rows with chunk_index+content."""
    doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.deleted_at:
        raise HTTPException(status_code=404, detail="Document deleted")
    require_document_access(db, current_user, doc)

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
def generate_document_metadata(document_id: str, db: DbSession, current_user: CurrentUser):
    """Generate GPT metadata from document chunks (title, description, doc_type, tags, taxonomy). Runs once chunks exist."""
    doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.deleted_at:
        raise HTTPException(status_code=404, detail="Document deleted")
    require_document_access(db, current_user, doc)
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
def get_document(document_id: str, db: DbSession, current_user: CurrentUser):
    """Get document metadata."""
    doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.deleted_at:
        raise HTTPException(status_code=404, detail="Document deleted")
    require_document_access(db, current_user, doc)
    return doc


@router.patch("/{document_id}", response_model=DocumentResponse)
def update_document(document_id: str, body: DocumentUpdate, db: DbSession, current_user: CurrentUserOptional):
    """Update document metadata (title, description, doc_type, tags, taxonomy). Admin/Super Admin or uploader only. Soft-deleted docs return 404."""
    doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.deleted_at:
        raise HTTPException(status_code=404, detail="Document deleted")
    _require_can_modify_document(current_user, doc)

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
def download_document(document_id: str, db: DbSession, current_user: CurrentUser):
    """Download file from S3 or return 404 if stored locally."""
    doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.deleted_at:
        raise HTTPException(status_code=404, detail="Document deleted")
    require_document_access(db, current_user, doc)

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
def delete_document(document_id: str, db: DbSession, current_user: CurrentUserOptional):
    """Soft-delete document and remove chunks from Qdrant. Admin/Super Admin or uploader only."""
    doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.deleted_at:
        return Message(message="Already deleted")
    _require_can_modify_document(current_user, doc)

    doc.deleted_at = datetime.now(timezone.utc)
    doc.status = DocumentStatus.deleted
    # Remove chunks from DB (cascade would work on hard delete; we explicit-delete for soft delete)
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    db.commit()

    try:
        delete_document_chunks(doc.project_id, doc.id)
    except Exception as e:
        logger.warning("Qdrant delete chunks failed: %s", e)

    return Message(message="Deleted")
