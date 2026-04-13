"""Project and document access checks (membership, uploads, privileged roles)."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.project import Project, ProjectMember
from app.models.user import User, UserRole


def is_privileged(user: User) -> bool:
    """Super Admin or Admin (manager) — full org access."""
    return user.role in (UserRole.admin, UserRole.manager)


def get_accessible_project_ids(db: Session, user: User) -> set[str] | None:
    """
    Project ids the user may access. None means all projects (privileged).
    Non-privileged: explicit project_members rows plus projects where the user has uploaded a document.
    """
    if is_privileged(user):
        return None
    member_rows = db.execute(
        select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    ).scalars().all()
    upload_rows = db.execute(
        select(Document.project_id)
        .where(Document.uploaded_by == user.id, Document.deleted_at.is_(None))
        .distinct()
    ).scalars().all()
    return set(member_rows) | set(upload_rows)


def require_authenticated(current_user: User | None) -> User:
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return current_user


def require_project_access(db: Session, user: User, project_id: str) -> None:
    """Raise 403 if the user cannot access this project."""
    ids = get_accessible_project_ids(db, user)
    if ids is None:
        return
    if project_id not in ids:
        raise HTTPException(status_code=403, detail="Access denied")


def document_is_accessible(db: Session, user: User, doc: Document) -> bool:
    """True if the user may read or use this document (non-deleted)."""
    if doc.deleted_at is not None:
        return False
    if is_privileged(user):
        return True
    if doc.uploaded_by == user.id:
        return True
    ids = get_accessible_project_ids(db, user)
    if ids is None:
        return True
    return doc.project_id in ids


def require_document_access(db: Session, user: User, doc: Document) -> None:
    if not document_is_accessible(db, user, doc):
        raise HTTPException(status_code=403, detail="Access denied")


def get_project_or_404(db: Session, project_id: str):
    project = db.execute(
        select(Project).where(Project.id == project_id, Project.is_deleted == False)
    ).scalars().one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
