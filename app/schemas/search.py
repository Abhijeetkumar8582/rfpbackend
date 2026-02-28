"""Search schemas."""
from datetime import datetime
from pydantic import BaseModel


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


class SearchResponse(BaseModel):
    query_text: str
    project_id: str
    k: int
    results: list[SearchResultItem]


class SearchAnswerResponse(BaseModel):
    """Search + GPT answer (RAG): same as SearchResponse plus answer text and classified topic."""
    query_text: str
    project_id: str
    k: int
    results: list[SearchResultItem]
    answer: str
    topic: str | None = None


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
    results: list[SearchResultItem] | None = None  # RAG chunks used for the answer


class SearchQueryCreate(BaseModel):
    project_id: str
    query_text: str
    k: int = 5
    filters_json: dict | None = None
    results_count: int = 0
    latency_ms: int | None = None


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

    class Config:
        from_attributes = True
