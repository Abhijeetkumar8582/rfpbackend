"""Application configuration from environment."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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

    # OpenAI (embeddings + GPT categorization + doc metadata)
    openai_api_key: str = ""
    openai_base_url: str = ""  # optional, e.g. for Azure or proxy
    openai_embedding_model: str = "text-embedding-3-small"
    openai_chat_model: str = "gpt-4o-mini"

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
