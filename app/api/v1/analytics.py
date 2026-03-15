"""Analytics API — dashboard metrics from search_queries and ChromaDB."""
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter
from sqlalchemy import select, func, delete

from app.api.deps import DbSession
from app.models.search_query import SearchQuery
from app.models.project import Project
from app.models.endpoint_log import EndpointLog
from app.models.faq import FAQ
from app.schemas.analytics import (
    DashboardMetricsResponse,
    ChartDataResponse,
    DateCountPoint,
    DateValuePoint,
    StatusCountPoint,
    KnowledgeGapItem,
    KnowledgeGapsResponse,
    DateHourValuePoint,
    SaveFaqAnswersRequest,
    ValidateFaqAnswersRequest,
    ValidateFaqAnswersResponse,
    ValidateFaqAnswersResult,
    FaqItem,
    FaqListResponse,
)
from app.services.chroma import get_collection_count
from app.services.reasoning import validate_faq_answers as do_validate_faq_answers

router = APIRouter(prefix="/analytics", tags=["analytics"])

# Default time window for dashboard metrics
DEFAULT_DAYS = 28
LOW_CONFIDENCE_THRESHOLD = 0.65
HIGH_GAP_REASONS = frozenset({"no_results", "missing_topic", "insufficient_evidence"})
# Paths used for response-time metrics (endpoint_logs only)
# Paths used for response-time / latency analytics (endpoint_logs). Include both reasoning and reasoning/stream.
QUERY_PATHS = [
    "/api/v1/search/query",
    "/api/v1/search/answer",
    "/api/v1/search/reasoning",
    "/api/v1/search/reasoning/stream",
    "/api/v1/search/queries",
]


@router.get("/dashboard-metrics", response_model=DashboardMetricsResponse)
def get_dashboard_metrics(
    db: DbSession,
    project_id: str | None = None,
    days: int = DEFAULT_DAYS,
):
    """
    Return aggregated dashboard metrics from search_queries and ChromaDB.
    - project_id: optional; if omitted, aggregates all projects (corporate-level).
    - days: time window (default 28).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    q = select(SearchQuery).where(SearchQuery.datetime_ >= cutoff)
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
    if project_id:
        total_chunks_index = get_collection_count(project_id)
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


@router.get("/knowledge-gaps", response_model=KnowledgeGapsResponse)
def get_knowledge_gaps(
    db: DbSession,
    project_id: str | None = None,
    days: int = DEFAULT_DAYS,
):
    """
    Return the list of questions that were not answered by the search (knowledge gaps).
    Data is read only from the search_queries table for the given project_id.
    project_id is required so results are always scoped to the selected project.
    """
    # Require project_id so we never return another project's or fallback data
    pid = (project_id or "").strip()
    if not pid:
        return KnowledgeGapsResponse(items=[])

    # Ensure the project exists and is not deleted
    row = db.execute(select(Project.id).where(Project.id == pid, Project.is_deleted == False)).first()
    if not row:
        return KnowledgeGapsResponse(items=[])

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    q = select(SearchQuery).where(SearchQuery.datetime_ >= cutoff)
    queries = list(db.execute(q).scalars().all())

    items = []
    for sq in queries:
        if (sq.results_count or 0) == 0 or (sq.no_answer_reason or "").strip() in HIGH_GAP_REASONS:
            reason = (sq.no_answer_reason or "").strip() or None
            if (sq.results_count or 0) == 0 and not reason:
                reason = "no_results"
            items.append(
                KnowledgeGapItem(
                    id=sq.id,
                    query_text=sq.query_text or "",
                    datetime=sq.datetime_.isoformat() if sq.datetime_ else "",
                    no_answer_reason=reason,
                )
            )
    # Newest first
    items.sort(key=lambda x: x.datetime, reverse=True)

    return KnowledgeGapsResponse(items=items)


@router.post("/knowledge-gaps/validate-answers", response_model=ValidateFaqAnswersResponse)
def validate_faq_answers(body: ValidateFaqAnswersRequest):
    """
    Validate each question-answer pair: LLM rates 0-100 how well the answer addresses the question.
    Returns confidence per search_query_id. Frontend uses this before showing Save validated answer.
    """
    if not body.items:
        return ValidateFaqAnswersResponse(results=[])
    tuples_list = [
        (item.search_query_id, (item.question or "").strip(), (item.answer or "").strip())
        for item in body.items
    ]
    tuples_list = [(sid, q, a) for sid, q, a in tuples_list if q and a]
    if not tuples_list:
        return ValidateFaqAnswersResponse(results=[])
    raw = do_validate_faq_answers(tuples_list)
    results = [ValidateFaqAnswersResult(search_query_id=x["search_query_id"], confidence=x["confidence"]) for x in raw]
    return ValidateFaqAnswersResponse(results=results)


@router.post("/knowledge-gaps/save-answers")
def save_faq_answers(body: SaveFaqAnswersRequest, db: DbSession):
    """
    For each item with a non-empty answer: insert (question, answer) into FAQs with a new UUID,
    then delete the corresponding row from search_queries. This moves answered gap questions
    into the FAQs table and removes them from the gaps list.
    """
    saved = 0
    for item in body.items:
        answer_text = (item.answer or "").strip()
        if not answer_text:
            continue
        sq = db.execute(select(SearchQuery).where(SearchQuery.id == item.search_query_id)).scalars().one_or_none()
        if not sq:
            continue
        question_text = (sq.query_text or "").strip()
        if not question_text:
            continue
        faq = FAQ(question=question_text, answer=answer_text)
        db.add(faq)
        db.flush()  # get faqId if needed
        db.execute(delete(SearchQuery).where(SearchQuery.id == item.search_query_id))
        saved += 1
    db.commit()
    return {"saved": saved, "message": f"Saved {saved} answer(s) to FAQs and removed from gaps."}


@router.get("/faqs", response_model=FaqListResponse)
def list_faqs(db: DbSession):
    """Return all FAQs for the FAQs section (Contextual Document Segmentation)."""
    rows = db.execute(select(FAQ).order_by(FAQ.faqId)).scalars().all()
    items = [FaqItem(faqId=r.faqId, question=r.question or "", answer=r.answer or "") for r in rows]
    return FaqListResponse(items=items)


# Display labels for answer_status and feedback_status in charts
ANSWER_STATUS_LABEL = {
    "answered": "Answered",
    "unanswered": "Unanswered",
    "low_confidence": "Low confidence",
    "needs_clarification": "Needs clarification",
    "unsupported": "Other",
    "contradictory": "Other",
}
FEEDBACK_STATUS_LABEL = {
    "positive": "Positive",
    "negative": "Negative",
    "neutral": "Neutral / no feedback",
    "not_given": "Neutral / no feedback",
}


@router.get("/chart-data", response_model=ChartDataResponse)
def get_chart_data(
    db: DbSession,
    project_id: str | None = None,
    days: int = DEFAULT_DAYS,
):
    """
    Return chart-ready data: time-series and breakdowns for dashboard graphs.
    - project_id: optional; if omitted, aggregates all projects (corporate-level).
    - days: time window (default 28).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    q = select(SearchQuery).where(SearchQuery.datetime_ >= cutoff)
    queries = list(db.execute(q).scalars().all())

    # Search volume trend: count per day
    volume_by_date: dict[str, int] = defaultdict(int)
    for sq in queries:
        d = sq.datetime_.date().isoformat() if sq.datetime_ else None
        if d:
            volume_by_date[d] += 1
    search_volume_trend = [
        DateCountPoint(date=d, count=c) for d, c in sorted(volume_by_date.items())
    ]

    # Answer status breakdown: map DB status to display label, then count
    status_counts: dict[str, int] = defaultdict(int)
    for sq in queries:
        raw = (sq.answer_status or "").strip() or "unanswered"
        label = ANSWER_STATUS_LABEL.get(raw, "Other")
        status_counts[label] += 1
    answer_status_breakdown = [
        StatusCountPoint(status=s, count=c) for s, c in sorted(status_counts.items())
    ]

    # Confidence trend: avg confidence_json.overall per day
    conf_by_date: dict[str, list[float]] = defaultdict(list)
    for sq in queries:
        conf = sq.confidence_json or {}
        overall = conf.get("overall")
        if overall is not None and isinstance(overall, (int, float)):
            d = sq.datetime_.date().isoformat() if sq.datetime_ else None
            if d:
                conf_by_date[d].append(float(overall))
    confidence_trend = [
        DateValuePoint(date=d, value=sum(vals) / len(vals))
        for d, vals in sorted(conf_by_date.items())
        if vals
    ]

    # Response time trend: avg duration_ms per day from endpoint_logs (query endpoints only)
    trend_rows = db.execute(
        select(
            func.date(EndpointLog.ts).label("date"),
            func.avg(EndpointLog.duration_ms).label("avg_ms"),
        )
        .where(
            EndpointLog.ts >= cutoff,
            EndpointLog.path.in_(QUERY_PATHS),
            EndpointLog.duration_ms.isnot(None),
        )
        .group_by(func.date(EndpointLog.ts))
        .order_by(func.date(EndpointLog.ts))
    ).all()
    response_time_trend = [
        DateValuePoint(date=row.date.isoformat(), value=float(row.avg_ms))
        for row in trend_rows
        if row.avg_ms is not None
    ]

    # Response time heatmap: avg duration_ms per (date, hour) bucket from endpoint_logs
    # Only include search endpoints we care about.
    heatmap_rows = db.execute(
        select(
            func.date(EndpointLog.ts).label("date"),
            func.extract("hour", EndpointLog.ts).label("hour"),
            func.avg(EndpointLog.duration_ms).label("avg_ms"),
        )
        .where(
            EndpointLog.ts >= cutoff,
            EndpointLog.path.in_(QUERY_PATHS),
        )
        .group_by(func.date(EndpointLog.ts), func.extract("hour", EndpointLog.ts))
        .order_by(func.date(EndpointLog.ts), func.extract("hour", EndpointLog.ts))
    ).all()

    response_time_heatmap = [
        DateHourValuePoint(
            date=row.date.isoformat(),
            hour=int(row.hour),
            avg_ms=float(row.avg_ms),
        )
        for row in heatmap_rows
        if row.avg_ms is not None
    ]

    # Feedback sentiment: Positive, Negative, Neutral / no feedback
    feedback_counts: dict[str, int] = defaultdict(int)
    for sq in queries:
        raw = (sq.feedback_status or "").strip() or "not_given"
        label = FEEDBACK_STATUS_LABEL.get(raw, "Neutral / no feedback")
        feedback_counts[label] += 1
    # Merge "Neutral / no feedback" if we keyed both
    neutral_total = feedback_counts.get("Neutral / no feedback", 0)
    feedback_sentiment = [
        StatusCountPoint(status="Positive", count=feedback_counts.get("Positive", 0)),
        StatusCountPoint(status="Negative", count=feedback_counts.get("Negative", 0)),
        StatusCountPoint(status="Neutral / no feedback", count=neutral_total),
    ]

    return ChartDataResponse(
        search_volume_trend=search_volume_trend,
        answer_status_breakdown=answer_status_breakdown,
        confidence_trend=confidence_trend,
        response_time_trend=response_time_trend,
        feedback_sentiment=feedback_sentiment,
        response_time_heatmap=response_time_heatmap,
    )
