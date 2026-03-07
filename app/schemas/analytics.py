"""Dashboard analytics metrics schema."""
from pydantic import BaseModel


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
