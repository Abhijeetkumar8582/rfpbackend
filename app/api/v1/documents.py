"""Documents API — upload (embed → categorize → S3), list, get, delete."""
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession
from app.models.document import Document, DocumentStatus
from app.models.project import Project
from app.schemas.document import DocumentResponse
from app.schemas.common import IDResponse, Message
from app.services.text_extract import extract_text_from_file
from app.services.embeddings import get_embedding, embedding_to_json
from app.services.categorize import categorize_document
from app.services.s3 import s3_upload, build_s3_key

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentResponse])
def list_documents(db: DbSession, project_id: int | None = None, skip: int = 0, limit: int = 100):
    """List documents, optionally by project. TODO: add auth, filter by access."""
    q = select(Document).where(Document.deleted_at.is_(None))
    if project_id is not None:
        q = q.where(Document.project_id == project_id)
    q = q.offset(skip).limit(limit).order_by(Document.uploaded_at.desc())
    return list(db.execute(q).scalars().all())


@router.post("", response_model=IDResponse)
async def upload_document(
    db: DbSession,
    project_id: int = Form(...),
    uploaded_by: int = Form(...),
    file: UploadFile = File(...),
):
    """
    Upload: embed content → GPT categorizes → update SQL → upload to S3.
    File is stored in S3 at project_id/cluster/filename so file repo shows correct folder.
    """
    filename = file.filename or "document"
    content_type = file.content_type or "application/octet-stream"
    body = await file.read()
    size_bytes = len(body)

    # Ensure project exists
    project = db.execute(select(Project).where(Project.id == project_id)).scalars().one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    doc = Document(
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
        # 1) Extract text for embedding + categorization
        text = extract_text_from_file(body, filename, content_type)

        # 2) Embed and store in SQL
        embedding = get_embedding(text)
        doc.embedding_json = embedding_to_json(embedding)
        db.commit()

        # 3) GPT assigns category → update SQL
        cluster = categorize_document(text, filename)
        doc.cluster = cluster
        db.commit()

        # 4) Upload to S3 at project_id/cluster/filename (correct folder in file repo)
        s3_key = build_s3_key(project_id, cluster, filename)
        s3_upload(body, s3_key, content_type)

        doc.storage_path = s3_key
        doc.status = DocumentStatus.ingested
        doc.ingested_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(doc)
    except ValueError as e:
        doc.status = DocumentStatus.failed
        db.commit()
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        doc.status = DocumentStatus.failed
        db.commit()
        raise HTTPException(status_code=500, detail=f"Processing failed: {e!s}")

    return IDResponse(id=doc.id)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: int, db: DbSession):
    """Get document metadata. TODO: check project access."""
    doc = db.execute(select(Document).where(Document.id == document_id)).scalars().one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{document_id}/download")
def download_document(document_id: int, db: DbSession):
    """Stream or redirect to file. TODO: check access, return file."""
    raise NotImplementedError("TODO: implement download document")


@router.delete("/{document_id}", response_model=Message)
def delete_document(document_id: int, db: DbSession):
    """Soft-delete document. TODO: check permission."""
    raise NotImplementedError("TODO: implement delete document")
