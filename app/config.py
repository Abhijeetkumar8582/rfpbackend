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
    # Public base URL for links in API responses (e.g. source PDF open URL when s3_url is absent)
    backend_public_url: str = "http://127.0.0.1:8000"

    # JWT — access and refresh both align to a 6-hour session window (override via env).
    access_token_expire_minutes: int = 360
    refresh_token_expire_hours: int = 6
    jwt_algorithm: str = "HS256"

    database_url: str = "sqlite:///./rfp.db"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Field encryption (for storing API credentials safely in DB)
    # Recommended: 32-byte key, base64 encoded (optionally prefixed with "base64:").
    # Example (generate): python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
    credentials_encryption_key: str = ""

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

    # Qdrant (vector store)
    # Default: on-disk embedded storage (no server on 6333). Same idea as pdf_qdrant_api.py --path.
    # Set to "-", "none", or "remote" (case-insensitive) to use qdrant_url only (Qdrant Cloud / local server).
    qdrant_local_path: str = ".qdrant_local"
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str = ""
    qdrant_collection_prefix: str = "folder"
    # Per-user Qdrant collections: vd_{slug}_{user_id} — slug from display name
    qdrant_user_collection_prefix: str = "vd"
    qdrant_timeout_sec: int = 30
    hybrid_dense_weight: float = 0.75
    hybrid_sparse_weight: float = 0.25
    # When true and qdrant_url points at localhost, the backend spawns a local qdrant process on startup
    # if none is already reachable. Set false if you use a remote Qdrant or start Qdrant yourself.
    qdrant_auto_start: bool = True
    # Path to qdrant executable; empty = look for "qdrant" / "qdrant.exe" on PATH
    qdrant_binary_path: str = ""
    # On-disk storage for the embedded process; empty = <backend_root>/.qdrant_storage
    qdrant_storage_path: str = ""

    # Chunking (word-based: 100, 200 words per chunk)
    chunk_size_words: int = 200
    chunk_overlap_words: int = 30

    # PDF OCR (optional: path to Tesseract executable if not in PATH, e.g. C:/ Program Files/Tesseract-OCR/tesseract.exe)
    tesseract_cmd: str = ""

    # SendGrid (email)
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@example.com"
    sendgrid_from_name: str = "RFP Backend"

    # Frontend + invites
    frontend_base_url: str = "http://localhost:3000"
    product_name: str = "RFP Platform"
    invite_token_hours: int = 48

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
