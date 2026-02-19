"""Projects API — CRUD and members."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession
from app.models.project import Project
from app.models.document import Document
from app.models.document_chunk import DocumentChunk

from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse, TrainDatasourceConfig, TrainDatasourceResponse
from app.schemas.common import IDResponse, Message
from app.services.chroma import sync_project_chunks_to_chroma

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
def list_projects(db: DbSession, skip: int = 0, limit: int = 100):
    """List projects (non-deleted). TODO: filter by membership, add auth."""
    q = select(Project).where(Project.is_deleted == False).offset(skip).limit(limit).order_by(Project.created_at.desc())
    return list(db.execute(q).scalars().all())


@router.post("", response_model=IDResponse)
def create_project(body: ProjectCreate, db: DbSession):
    """Create project. TODO: add auth, set creator as member."""
    proj = Project(
        name=body.name,
        description=body.description,
        retention_days=body.retention_days,
        auto_delete_enabled=body.auto_delete_enabled,
        is_deleted=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    return IDResponse(id=proj.id)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: DbSession):
    """Get project by id. TODO: check membership."""
    raise NotImplementedError("TODO: implement get project")


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: int, body: ProjectUpdate, db: DbSession):
    """Update project. TODO: check permission."""
    raise NotImplementedError("TODO: implement update project")


@router.delete("/{project_id}", response_model=Message)
def delete_project(project_id: int, db: DbSession):
    """Soft-delete project. TODO: check permission."""
    raise NotImplementedError("TODO: implement delete project")


@router.post("/{project_id}/train-datasource", response_model=TrainDatasourceResponse)
def train_datasource(project_id: int, db: DbSession, body: TrainDatasourceConfig | None = Body(None)):
    """
    Fetch all document chunks and their stored embeddings from the DB and push to ChromaDB.
    Upload already stores chunks + embeddings in document_chunks; train re-syncs that data
    into the project's Chroma collection (clear then add all). No re-embedding — uses DB embeddings.
    """
    project = db.execute(select(Project).where(Project.id == project_id, Project.is_deleted == False)).scalars().one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Fetch all documents in this project that have chunk rows (content + embeddings_json from upload)
    docs = db.execute(
        select(Document, DocumentChunk)
        .join(DocumentChunk, Document.id == DocumentChunk.document_id)
        .where(Document.project_id == project_id, Document.deleted_at.is_(None))
    ).all()

    # Build rows: (document_id, filename, content_json, embeddings_json) — all from DB
    rows = [
        (doc.id, doc.filename, chunk_row.content, chunk_row.embeddings_json)
        for doc, chunk_row in docs
    ]

    documents_synced, chunks_synced = sync_project_chunks_to_chroma(project_id, rows)
    return TrainDatasourceResponse(
        message="Datasource trained: all document chunks synced to ChromaDB.",
        documents_synced=documents_synced,
        chunks_synced=chunks_synced,
    )


@router.get("/{project_id}/members")
def list_project_members(project_id: int, db: DbSession):
    """List project members. TODO: check membership, return user info."""
    raise NotImplementedError("TODO: implement list project members")


@router.post("/{project_id}/members/{user_id}", response_model=Message)
def add_project_member(project_id: int, user_id: uuid.UUID, db: DbSession):
    """Add user to project. TODO: check permission."""
    raise NotImplementedError("TODO: implement add project member")


@router.delete("/{project_id}/members/{user_id}", response_model=Message)
def remove_project_member(project_id: int, user_id: uuid.UUID, db: DbSession):
    """Remove user from project. TODO: check permission."""
    raise NotImplementedError("TODO: implement remove project member")
