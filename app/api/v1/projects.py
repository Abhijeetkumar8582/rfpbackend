"""Projects API — CRUD and members."""
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession, CurrentUser, CurrentUserOptional, require_admin_or_manager
from app.core.project_access import get_accessible_project_ids, get_project_or_404, require_project_access
from app.core.project_id import generate_project_id
from app.models.project import Project, ProjectMember
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.user import User

from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse, TrainDatasourceConfig, TrainDatasourceResponse
from app.schemas.document import DocumentResponse
from app.schemas.common import IDResponse, Message
from app.services.qdrant import sync_project_chunks_to_qdrant

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
def list_projects(db: DbSession, current_user: CurrentUser, skip: int = 0, limit: int = 100):
    """List projects the caller may access (membership, prior uploads, or all for admins)."""
    q = select(Project).where(Project.is_deleted == False)
    accessible = get_accessible_project_ids(db, current_user)
    if accessible is not None:
        if not accessible:
            return []
        q = q.where(Project.id.in_(accessible))
    q = q.offset(skip).limit(limit).order_by(Project.created_at.desc())
    return list(db.execute(q).scalars().all())


@router.post("", response_model=IDResponse)
def create_project(body: ProjectCreate, db: DbSession, current_user: CurrentUser):
    """Create project and add the creator as a member."""
    proj = Project(
        id=generate_project_id(db),
        name=body.name,
        description=body.description,
        retention_days=body.retention_days,
        auto_delete_enabled=body.auto_delete_enabled,
        is_deleted=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(proj)
    db.flush()
    db.add(
        ProjectMember(
            project_id=proj.id,
            user_id=current_user.id,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    db.refresh(proj)
    return IDResponse(id=proj.id)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, db: DbSession, current_user: CurrentUser):
    """Get project by id."""
    project = get_project_or_404(db, project_id)
    require_project_access(db, current_user, project_id)
    return project


@router.get("/{project_id}/documents", response_model=list[DocumentResponse])
def list_project_documents(
    project_id: str,
    db: DbSession,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 100,
):
    """List RFP documents for a project (non-deleted)."""
    get_project_or_404(db, project_id)
    require_project_access(db, current_user, project_id)
    q = (
        select(Document)
        .where(Document.project_id == project_id, Document.deleted_at.is_(None))
        .offset(skip)
        .limit(limit)
        .order_by(Document.uploaded_at.desc())
    )
    return list(db.execute(q).scalars().all())


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: str, body: ProjectUpdate, db: DbSession, current_user: CurrentUser):
    """Update project settings."""
    project = get_project_or_404(db, project_id)
    require_project_access(db, current_user, project_id)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.retention_days is not None:
        project.retention_days = body.retention_days
    if body.auto_delete_enabled is not None:
        project.auto_delete_enabled = body.auto_delete_enabled
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", response_model=Message)
def delete_project(project_id: str, db: DbSession, current_user: CurrentUser):
    """Soft-delete project."""
    project = get_project_or_404(db, project_id)
    require_project_access(db, current_user, project_id)
    project.is_deleted = True
    db.commit()
    return Message(message="Project deleted")


@router.post("/{project_id}/train-datasource", response_model=TrainDatasourceResponse)
def train_datasource(
    project_id: str,
    db: DbSession,
    current_user: CurrentUserOptional,
    body: TrainDatasourceConfig | None = Body(None),
):
    """
    1) Saves optional ingestion defaults on the project (used for **new** uploads: chunk size / overlap).
    2) Rebuilds the Qdrant collection for this project from DB chunks and stored embeddings (no re-embedding).

    Only Super Admin or Admin.
    """
    require_admin_or_manager(current_user)
    project = db.execute(select(Project).where(Project.id == project_id, Project.is_deleted == False)).scalars().one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    cfg = body or TrainDatasourceConfig()
    if cfg.chunk_size_words is not None:
        project.chunk_size_words = cfg.chunk_size_words
    if cfg.chunk_overlap_words is not None:
        project.chunk_overlap_words = cfg.chunk_overlap_words
    if cfg.include_metadata is not None:
        project.include_metadata_in_retrieval = cfg.include_metadata
    db.commit()
    db.refresh(project)

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

    documents_synced, chunks_synced = sync_project_chunks_to_qdrant(project_id, rows)
    return TrainDatasourceResponse(
        message="Search index rebuilt from database chunks and synced to Qdrant.",
        documents_synced=documents_synced,
        chunks_synced=chunks_synced,
        chunk_size_words=project.chunk_size_words,
        chunk_overlap_words=project.chunk_overlap_words,
        include_metadata_in_retrieval=project.include_metadata_in_retrieval,
    )


@router.get("/{project_id}/members")
def list_project_members(project_id: str, db: DbSession, current_user: CurrentUser):
    """List project members (user id, name, email)."""
    get_project_or_404(db, project_id)
    require_project_access(db, current_user, project_id)
    rows = db.execute(
        select(ProjectMember, User)
        .join(User, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.created_at.asc())
    ).all()
    return [
        {"user_id": u.id, "name": u.name, "email": u.email}
        for _m, u in rows
    ]


@router.post("/{project_id}/members/{user_id}", response_model=Message)
def add_project_member(project_id: str, user_id: str, db: DbSession, current_user: CurrentUserOptional):
    """Add user to project. Super Admin or Admin only."""
    require_admin_or_manager(current_user)
    get_project_or_404(db, project_id)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    existing = db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ).scalars().first()
    if existing:
        return Message(message="User is already a member")
    db.add(
        ProjectMember(
            project_id=project_id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    return Message(message="Member added")


@router.delete("/{project_id}/members/{user_id}", response_model=Message)
def remove_project_member(project_id: str, user_id: str, db: DbSession, current_user: CurrentUserOptional):
    """Remove user from project. Super Admin or Admin only."""
    require_admin_or_manager(current_user)
    get_project_or_404(db, project_id)
    row = db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Membership not found")
    db.delete(row)
    db.commit()
    return Message(message="Member removed")
