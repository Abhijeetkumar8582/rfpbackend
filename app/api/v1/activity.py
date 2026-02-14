"""Activity logs API — list activity stream (stub)."""
from fastapi import APIRouter
from app.api.deps import DbSession

from app.schemas.activity import ActivityLogResponse

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("/logs", response_model=list[ActivityLogResponse])
def list_activity_logs(
    db: DbSession,
    project_id: int | None = None,
    activity_type: str | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """List activity logs. TODO: add auth, filters."""
    raise NotImplementedError("TODO: implement list activity logs")
