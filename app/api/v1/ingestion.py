"""Ingestion jobs API — list, get, trigger (stubs)."""
from fastapi import APIRouter
from app.api.deps import DbSession

from app.schemas.ingestion import IngestionJobResponse
from app.schemas.common import IDResponse, Message

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.get("/jobs", response_model=list[IngestionJobResponse])
def list_ingestion_jobs(db: DbSession, project_id: str | None = None, document_id: str | None = None, skip: int = 0, limit: int = 100):
    """List ingestion jobs. TODO: filter by project/document, add auth."""
    raise NotImplementedError("TODO: implement list ingestion jobs")


@router.get("/jobs/{job_id}", response_model=IngestionJobResponse)
def get_ingestion_job(job_id: int, db: DbSession):
    """Get ingestion job by id. TODO: check project access."""
    raise NotImplementedError("TODO: implement get ingestion job")


@router.post("/jobs", response_model=IDResponse)
def create_ingestion_job(db: DbSession, project_id: str, document_id: str | None = None):
    """Create and optionally start ingestion job. TODO: implement worker trigger."""
    raise NotImplementedError("TODO: implement create ingestion job")


@router.post("/jobs/{job_id}/retry", response_model=Message)
def retry_ingestion_job(job_id: int, db: DbSession):
    """Retry failed job. TODO: implement."""
    raise NotImplementedError("TODO: implement retry ingestion job")
