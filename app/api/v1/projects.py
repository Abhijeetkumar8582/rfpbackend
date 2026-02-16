"""Projects API — CRUD and members."""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession
from app.models.project import Project

from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse
from app.schemas.common import IDResponse, Message

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


@router.get("/{project_id}/members")
def list_project_members(project_id: int, db: DbSession):
    """List project members. TODO: check membership, return user info."""
    raise NotImplementedError("TODO: implement list project members")


@router.post("/{project_id}/members/{user_id}", response_model=Message)
def add_project_member(project_id: int, user_id: int, db: DbSession):
    """Add user to project. TODO: check permission."""
    raise NotImplementedError("TODO: implement add project member")


@router.delete("/{project_id}/members/{user_id}", response_model=Message)
def remove_project_member(project_id: int, user_id: int, db: DbSession):
    """Remove user from project. TODO: check permission."""
    raise NotImplementedError("TODO: implement remove project member")
