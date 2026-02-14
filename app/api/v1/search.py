"""Search API — semantic search and query logging (stubs)."""
from fastapi import APIRouter
from app.api.deps import DbSession

from app.schemas.search import SearchRequest, SearchQueryResponse

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/query")
def search(body: SearchRequest, db: DbSession, project_id: int | None = None):
    """Run semantic search; log to search_queries. TODO: vector search, return results + log."""
    raise NotImplementedError("TODO: implement search query")


@router.get("/queries", response_model=list[SearchQueryResponse])
def list_search_queries(db: DbSession, project_id: int | None = None, skip: int = 0, limit: int = 100):
    """List recent search queries. TODO: add auth, filter by user/project."""
    raise NotImplementedError("TODO: implement list search queries")
