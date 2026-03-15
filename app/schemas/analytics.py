"""Dashboard analytics metrics schema."""
from pydantic import BaseModel


class DateCountPoint(BaseModel):
    date: str  # YYYY-MM-DD
    count: int


class DateValuePoint(BaseModel):
    date: str  # YYYY-MM-DD
    value: float  # avg_confidence or avg_latency_ms


class StatusCountPoint(BaseModel):
    status: str
    count: int


class DateHourValuePoint(BaseModel):
    """Average latency per (date, hour) bucket for heat map visualizations."""
    date: str  # YYYY-MM-DD
    hour: int  # 0–23
    avg_ms: float


class ChartDataResponse(BaseModel):
    """Time-series and breakdown data for dashboard charts."""
    search_volume_trend: list["DateCountPoint"] = []  # total searches per day
    answer_status_breakdown: list["StatusCountPoint"] = []  # Answered, Unanswered, Low confidence, etc.
    confidence_trend: list["DateValuePoint"] = []  # avg confidence per day (value 0–1)
    response_time_trend: list["DateValuePoint"] = []  # avg latency_ms per day
    feedback_sentiment: list["StatusCountPoint"] = []  # Positive, Negative, Neutral / no feedback
    response_time_heatmap: list["DateHourValuePoint"] = []  # avg latency per (date, hour) bucket for heat map


class KnowledgeGapItem(BaseModel):
    """A single question that was not answered by the search (knowledge gap)."""
    id: int  # search_queries.id — used when saving answers to FAQs and deleting from search_queries
    query_text: str  # the question that had no / insufficient results
    datetime: str  # ISO timestamp (column name in search_queries)
    no_answer_reason: str | None  # no_results | missing_topic | insufficient_evidence | null if no_results only


class KnowledgeGapsResponse(BaseModel):
    """List of questions that were not answered by search (knowledge gaps)."""
    items: list[KnowledgeGapItem] = []


class SaveFaqAnswersItem(BaseModel):
    """One question-answer pair to save to FAQs and remove from search_queries."""
    search_query_id: int
    answer: str


class SaveFaqAnswersRequest(BaseModel):
    """Request body for saving Review gaps answers to FAQs."""
    items: list[SaveFaqAnswersItem] = []


class ValidateFaqAnswersItem(BaseModel):
    """One question-answer pair to validate (relevance check)."""
    search_query_id: int
    question: str
    answer: str


class ValidateFaqAnswersRequest(BaseModel):
    """Request body for validating FAQ answers before save."""
    items: list[ValidateFaqAnswersItem] = []


class ValidateFaqAnswersResult(BaseModel):
    """Per-item validation result."""
    search_query_id: int
    confidence: int  # 0-100


class ValidateFaqAnswersResponse(BaseModel):
    """Response from validate-faq-answers API."""
    results: list[ValidateFaqAnswersResult] = []


class FaqItem(BaseModel):
    """One FAQ row from the FAQs table."""
    faqId: str
    question: str
    answer: str


class FaqListResponse(BaseModel):
    """List of all FAQs for Contextual Document Segmentation / FAQs section."""
    items: list[FaqItem] = []


class DashboardMetricsResponse(BaseModel):
    """Aggregated metrics for the dashboard (optionally scoped by project and time window)."""
    overall_answer_accuracy: float  # 0–1; from feedback or answer_status
    total_questions_answered: int
    total_unanswered_questions: int
    total_active_users: int  # distinct users who asked questions in window
    average_confidence_score: float  # 0–1
    search_success_rate: float  # 0–1; queries with results_count > 0
    low_confidence_answers: int  # count where overall confidence < 0.65
    average_response_time_ms: float | None  # avg latency_ms
    high_severity_knowledge_gaps: int  # high-priority gaps (no_results, missing_topic, insufficient_evidence)
    total_chunks_index: int  # total chunks in ChromaDB (for selected project(s))
