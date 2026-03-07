"""Search schemas."""
from datetime import datetime
from pydantic import BaseModel, field_validator, field_validator, field_validator


class SearchRequest(BaseModel):
    query_text: str
    project_id: str
    k: int = 5
    filters_json: dict | None = None


class SearchResultItem(BaseModel):
    """One chunk hit from ChromaDB (question embedding vs document chunk embeddings)."""
    content: str
    document_id: str
    filename: str
    chunk_index: int
    distance: float
    score: float  # 1 - distance for cosine-like; higher = more similar


class SourceItem(BaseModel):
    """One source cited in the RAG answer."""
    document_id: str
    title: str = ""  # Human-readable doc title (e.g. filename without extension)
    filename: str
    chunk_id: str  # e.g. "doc_xxx:12" or "doc_xxx_chunk_12"
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None
    snippet: str  # Truncated content preview
    score: float


class ConfidenceScores(BaseModel):
    """Confidence metrics for the RAG answer."""
    overall: float = 0.0  # 0–1 overall confidence
    retrieval_avg_top3: float = 0.0  # Avg similarity of top 3 chunks
    evidence_coverage: float = 0.0  # 0–1 how well passages support the answer
    contradiction_risk: float = 0.0  # 0–1 risk of contradictions


class SearchResponse(BaseModel):
    query_text: str
    project_id: str
    k: int
    results: list[SearchResultItem]


class SearchAnswerResponse(BaseModel):
    """Search + GPT answer (RAG): same as SearchResponse plus answer, topics, sources, confidence."""
    query_text: str
    project_id: str
    k: int
    results: list[SearchResultItem]
    answer: str
    topics_covered: list[str] = []
    sources: list[SourceItem] = []
    confidence: ConfidenceScores = ConfidenceScores()
    search_query_id: int | None = None  # For feedback submission


class ChatMessage(BaseModel):
    """One message in a chat/completion request (OpenAI-style)."""
    role: str  # "user", "assistant", "system"
    content: str


class SearchChatRequest(BaseModel):
    """Chat/completion-style request: messages + project context."""
    messages: list[ChatMessage]
    project_id: str
    k: int = 5
    filters_json: dict | None = None


class ChatChoiceMessage(BaseModel):
    role: str = "assistant"
    content: str


class SearchChatResponse(BaseModel):
    """Chat/completion-style response: choices with message, plus optional search results."""
    id: str | None = None
    choices: list[dict]  # [{ "message": { "role": "assistant", "content": "..." } }]
    results: list[SearchResultItem] | None = None
    sources: list[SourceItem] = []
    confidence: ConfidenceScores = ConfidenceScores()


class SearchQueryCreate(BaseModel):
    project_id: str
    query_text: str
    k: int = 5
    filters_json: dict | None = None
    results_count: int = 0
    latency_ms: int | None = None


class SearchFeedbackRequest(BaseModel):
    """Submit feedback for a search query. Overwrites any existing feedback."""
    feedback_status: str  # positive | negative | neutral | not_given
    feedback_score: int  # 1 = helpful, 0 = neutral, -1 = not helpful
    feedback_reason: str | None = None  # incomplete_answer | wrong_policy | missing_info | etc.
    feedback_text: str | None = None  # Optional free-text comment

    def model_post_init(self, __context) -> None:
        if self.feedback_status not in ("positive", "negative", "neutral", "not_given"):
            raise ValueError("feedback_status must be positive, negative, neutral, or not_given")
        if self.feedback_score not in (1, 0, -1):
            raise ValueError("feedback_score must be 1, 0, or -1")


class SearchQueryResponse(BaseModel):
    id: int
    ts: datetime
    actor_user_id: str | None
    project_id: str
    query_text: str
    k: int
    results_count: int
    latency_ms: int | None
    answer: str | None = None
    topic: str | None = None
    sources_json: list | None = None
    confidence_json: dict | None = None
    sources_document_metadata_json: list | None = None  # [{document_id, title, doc_type, domain, folder_id, folder_path, uploaded_at, updated_at, status, language, tags}, ...]
    answer_status: str | None = None  # answered | low_confidence | unanswered | needs_clarification | unsupported | contradictory
    no_answer_reason: str | None = None  # no_results | low_retrieval_score | insufficient_evidence | missing_topic | language_mismatch | conflicting_sources | needs_user_clarification
    feedback_status: str | None = None  # positive | negative | neutral | not_given
    feedback_score: int | None = None  # 1 | 0 | -1
    feedback_reason: str | None = None
    feedback_text: str | None = None
    feedback_at: datetime | None = None

    class Config:
        from_attributes = True


# --- Reasoning API (agentic search) ---


class ReasoningRequest(BaseModel):
    """Request for /search/reasoning (agentic RAG pipeline)."""
    query_text: str
    project_id: str
    k: int = 20  # Chunks to retrieve (before reranking)
    top_k: int = 12  # After reranking, how many to pass to synthesis
    skip_self_check: bool = False  # Optional: skip self-check for faster response


class QueryAnalysis(BaseModel):
    """Structured query understanding from Layer 1."""
    intent: str = ""
    domain: str = ""
    answer_type: str = ""
    constraints: dict = {}
    missing_constraints: list[str] = []


class IntelligenceHubTopic(BaseModel):
    """Most searched topic from search_queries."""
    topic: str
    count: int


class IntelligenceHubLowConfidence(BaseModel):
    """Search with low AI confidence (from confidence_json.overall)."""
    section: str  # query_text
    confidence: int  # 0-100


class IntelligenceHubHighConfidence(BaseModel):
    """Topic/section where AI has high confidence (from confidence_json.overall)."""
    section: str  # topic or query_text
    confidence: int  # 0-100


class IntelligenceHubGap(BaseModel):
    """Gap in knowledge — query with few/no results or low confidence."""
    area: str
    priority: str  # "high" | "medium" | "low"


class IntelligenceHubRecentDoc(BaseModel):
    """Recently uploaded document."""
    id: str  # document id for unique React keys
    name: str
    time: str  # human-readable, e.g. "2 min ago"
    size: str  # human-readable, e.g. "2.4 MB"


class IntelligenceHubResponse(BaseModel):
    """Intelligence Hub dashboard data from search_queries and documents."""
    most_searched_topics: list[IntelligenceHubTopic] = []
    low_confidence_areas: list[IntelligenceHubLowConfidence] = []
    high_confidence_areas: list[IntelligenceHubHighConfidence] = []
    gaps_in_knowledge: list[IntelligenceHubGap] = []
    recently_uploaded: list[IntelligenceHubRecentDoc] = []


class ReasoningResponse(BaseModel):
    """Response from /search/reasoning with full pipeline output."""
    query_text: str
    project_id: str
    results: list[SearchResultItem]
    answer: str
    topics_covered: list[str] = []
    sources: list[SourceItem] = []
    confidence: ConfidenceScores = ConfidenceScores()
    uncertainty_note: str | None = None
    missing_info_note: str | None = None
    query_analysis: QueryAnalysis | None = None
    self_check_passed: bool = True
    self_check_issues: list[str] = []
    clarification_suggested: bool = False
    search_query_id: int | None = None  # For feedback submission
