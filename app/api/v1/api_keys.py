"""API keys API — create, list, revoke (stubs)."""
from fastapi import APIRouter
from app.api.deps import DbSession

from app.schemas.common import IDResponse, Message

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("", response_model=list[dict])
def list_api_keys(db: DbSession):
    """List API keys for current user/org. TODO: add auth, never return key value."""
    raise NotImplementedError("TODO: implement list api keys")


@router.post("", response_model=dict)
def create_api_key(db: DbSession, name: str):
    """Create API key; return key once (then only hash stored). TODO: implement."""
    raise NotImplementedError("TODO: implement create api key")


@router.delete("/{key_id}", response_model=Message)
def revoke_api_key(key_id: int, db: DbSession):
    """Revoke API key. TODO: implement."""
    raise NotImplementedError("TODO: implement revoke api key")
