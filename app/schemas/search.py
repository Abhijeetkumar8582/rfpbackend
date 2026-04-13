"""Search schemas."""
from datetime import datetime
from pydantic import BaseModel, Field, model_validator


class SearchBalance(BaseModel):
    """Hybrid retrieval weights from the Search balance UI (Text / Vector / Rerank), total 100%."""

    text_pct: int = Field(..., ge=5, le=90)
    vector_pct: int = Field(..., ge=5, le=90)
    rerank_pct: int = Field(..., ge=5, le=90)

    @model_validator(mode="after")
    def must_sum_to_100(self):
        if self.text_pct + self.vector_pct + self.rerank_pct != 100:
            raise ValueError("text_pct, vector_pct, and rerank_pct must sum to 100")
        return self


class SearchRequest(BaseModel):
    query_text: str
    project_id: str
    k: int = 5
    filters_json: dict | None = None
    advanced_search: bool = False  # When True, run Query Intelligence Layer before retrieval
    conversation_id: str | None = None  # Optional; same id for follow-up queries (valid 24h)
    search_balance: SearchBalance | None = None  # When set, fuse keyword / vector / cross-encoder scores (answer path)


class SearchResultItem(BaseModel):
    """One chunk hit from ChromaDB (question embedding vs document chunk embeddings)."""
    content: str
    document_id: str
    filename: str
    chunk_index: int
    section: str | None = None
    breadcrumb: str | None = None
    page_start: int | None = None  # 1-based PDF page (when indexed with page map)
    page_end: int | None = None
    source_url: str | None = None  # document URL with #page=N when available
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
    source_url: str | None = None  # Open PDF at page (s3_url or API download + #page=)


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
    # Advanced search (Query Intelligence) — optional
    advanced_search_used: bool = False
    cleaned_query: str | None = None
    clarification_needed: bool = False
    clarification_questions: list[str] = []


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
    conversation_id: str | None = None  # Set when search is saved; use for follow-up queries
    # Advanced search (Query Intelligence) — optional
    advanced_search_used: bool = False
    cleaned_query: str | None = None
    clarification_needed: bool = False
    clarification_questions: list[str] = []


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
    datetime_: datetime = Field(serialization_alias="ts")  # model column "datetime"; alias for API compat
    conversation_id: str  # Same id for all Q&A in one conversation; used to group and load full thread
    actor_user_id: str | None
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
    advanced_search: bool = False  # When True, use Query Intelligence Layer (cleanup, intent, split, rewrite, domain, filters, clarification, plan)
    conversation_id: str | None = None  # Optional; same id for follow-up queries (valid 24h)
    search_balance: SearchBalance | None = None  # When set, fuse keyword / vector / cross-encoder scores before synthesis


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


class IndexHealth(BaseModel):
    """Index health metrics for Intelligence Hub."""
    documents_indexed_pct: int  # 0-100, % of project docs that are ingested/indexed
    chunks_in_vector_db: int
    embedding_quality: str  # "Good" | "Fair" | "Poor"
    last_indexed_ago: str | None  # e.g. "5 min ago", or null if never indexed


class IntelligenceHubResponse(BaseModel):
    """Intelligence Hub dashboard data from search_queries and documents."""
    most_searched_topics: list[IntelligenceHubTopic] = []
    low_confidence_areas: list[IntelligenceHubLowConfidence] = []
    high_confidence_areas: list[IntelligenceHubHighConfidence] = []
    gaps_in_knowledge: list[IntelligenceHubGap] = []
    recently_uploaded: list[IntelligenceHubRecentDoc] = []
    index_health: IndexHealth | None = None


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
    clarification_questions: list[str] = []  # From Query Intelligence when advanced_search and clarification_needed
    search_query_id: int | None = None  # For feedback submission
    conversation_id: str | None = None  # Set when search is saved; use for follow-up queries
    advanced_search_used: bool = False
    cleaned_query: str | None = None
