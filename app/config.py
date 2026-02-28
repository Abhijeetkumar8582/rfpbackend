"""Application configuration from environment."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env from backend root (parent of app/) so it works whether you run
# uvicorn from backend/ or from project root (e.g. RFP/). test_gpt_apis.py
# uses backend/.env; the app must use the same file.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    secret_key: str = "change-me-in-production"
    api_v1_prefix: str = "/api/v1"

    # JWT
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    jwt_algorithm: str = "HS256"

    database_url: str = "sqlite:///./rfp.db"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # OpenAI — chat completions (search answer, doc metadata, rephrase, categorize)
    openai_api_key: str = ""  # token for chat (e.g. Druid JWT)
    openai_base_url: str = ""  # chat completions URL, e.g. .../deployments/gpt-4o-mini/chat/completions?api-version=...
    # OpenAI — embeddings (semantic search, separate URL + token when using different provider)
    openai_embedding_api_key: str = ""  # token for embeddings (e.g. OpenAI sk-proj-...); if empty, uses openai_api_key
    openai_embedding_base_url: str = ""  # embeddings URL; if empty, derived from openai_base_url
    openai_api_version: str = ""  # optional, e.g. 2024-06-01 for Azure/Druid
    openai_embedding_model: str = "text-embedding-3-small"
    openai_chat_model: str = "gpt-4o-mini"
    # Set to false if gateway (e.g. Druid) returns 400 for response_format
    openai_use_json_mode: bool = True
    # Set to true if gateway expects "model" in the request body (some Azure/Druid setups need it)
    openai_send_model_in_body: bool = False

    # S3 (file storage)
    s3_bucket: str = ""
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # ChromaDB (vector store — one client, one collection per folder/project)
    chroma_persist_path: str = "./chroma_data"

    # Chunking (word-based: 100, 200 words per chunk)
    chunk_size_words: int = 200
    chunk_overlap_words: int = 30

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
