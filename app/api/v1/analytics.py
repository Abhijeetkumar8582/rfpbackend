"""Analytics API — dashboard metrics from search_queries and ChromaDB."""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession
from app.models.search_query import SearchQuery
from app.models.project import Project
from app.schemas.analytics import DashboardMetricsResponse
from app.services.chroma import get_collection_count

router = APIRouter(prefix="/analytics", tags=["analytics"])

# Default time window for dashboard metrics
DEFAULT_DAYS = 28
LOW_CONFIDENCE_THRESHOLD = 0.65
HIGH_GAP_REASONS = frozenset({"no_results", "missing_topic", "insufficient_evidence"})


@router.get("/dashboard-metrics", response_model=DashboardMetricsResponse)
def get_dashboard_metrics(
    db: DbSession,
    project_id: str | None = None,
    days: int = DEFAULT_DAYS,
):
    """
    Return aggregated dashboard metrics from search_queries and ChromaDB.
    - project_id: optional; if omitted, uses first non-deleted project and aggregates chunks across all projects.
    - days: time window (default 28).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    pid = project_id
    if not pid:
        row = db.execute(select(Project.id).where(Project.is_deleted == False).limit(1)).first()
        pid = row[0] if row else None

    # Base query: all search_queries in window; optionally filter by project
    q = select(SearchQuery).where(SearchQuery.ts >= cutoff)
    if pid:
        q = q.where(SearchQuery.project_id == pid)
    queries = list(db.execute(q).scalars().all())

    total = len(queries)
    answered = sum(1 for sq in queries if (sq.answer_status or "").strip() == "answered")
    unanswered = sum(
        1 for sq in queries
        if (sq.answer_status or "").strip() not in ("", "answered")
    )
    with_feedback_positive = sum(1 for sq in queries if (sq.feedback_status or "").strip() == "positive")
    with_feedback_negative = sum(1 for sq in queries if (sq.feedback_status or "").strip() == "negative")
    feedback_total = with_feedback_positive + with_feedback_negative
    if feedback_total > 0:
        overall_answer_accuracy = with_feedback_positive / feedback_total
    else:
        # Fallback: use answer_status
        overall_answer_accuracy = (answered / total) if total else 0.0

    # Active users: distinct actor_user_id (non-null)
    active_user_ids = {sq.actor_user_id for sq in queries if sq.actor_user_id}
    total_active_users = len(active_user_ids)

    # Average confidence (overall from confidence_json)
    confidence_values = []
    for sq in queries:
        conf = sq.confidence_json or {}
        overall = conf.get("overall")
        if overall is not None and isinstance(overall, (int, float)):
            confidence_values.append(float(overall))
    average_confidence_score = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0

    # Search success: had at least one result
    with_results = sum(1 for sq in queries if (sq.results_count or 0) > 0)
    search_success_rate = (with_results / total) if total else 0.0

    # Low confidence answers (overall < threshold)
    low_confidence_answers = sum(
        1 for sq in queries
        if (sq.confidence_json or {}).get("overall") is not None
        and isinstance((sq.confidence_json or {}).get("overall"), (int, float))
        and float((sq.confidence_json or {}).get("overall")) < LOW_CONFIDENCE_THRESHOLD
    )

    # Average response time (latency_ms)
    latencies = [sq.latency_ms for sq in queries if sq.latency_ms is not None]
    average_response_time_ms = sum(latencies) / len(latencies) if latencies else None

    # High-severity knowledge gaps
    high_severity_knowledge_gaps = sum(
        1 for sq in queries
        if (sq.results_count or 0) == 0
        or (sq.no_answer_reason or "").strip() in HIGH_GAP_REASONS
    )

    # Total chunks: for one project, count that collection; else sum all non-deleted projects
    total_chunks_index = 0
    if pid:
        total_chunks_index = get_collection_count(pid)
    else:
        project_rows = db.execute(select(Project.id).where(Project.is_deleted == False)).all()
        for row in project_rows:
            proj_id = row[0]
            total_chunks_index += get_collection_count(proj_id)

    return DashboardMetricsResponse(
        overall_answer_accuracy=round(overall_answer_accuracy, 4),
        total_questions_answered=answered,
        total_unanswered_questions=unanswered,
        total_active_users=total_active_users,
        average_confidence_score=round(average_confidence_score, 4),
        search_success_rate=round(search_success_rate, 4),
        low_confidence_answers=low_confidence_answers,
        average_response_time_ms=round(average_response_time_ms, 2) if average_response_time_ms is not None else None,
        high_severity_knowledge_gaps=high_severity_knowledge_gaps,
        total_chunks_index=total_chunks_index,
    )
