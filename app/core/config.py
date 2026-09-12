from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # Hosted PostgreSQL (Supabase recommended for the zero-cost prototype).
    database_url: str

    # Hosted Qdrant. Cloud Inference creates embeddings server-side, so no
    # embedding model is downloaded to the developer machine.
    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection: str = "financial_knowledge"
    qdrant_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    qdrant_vector_name: str = "dense"
    qdrant_vector_size: int = 384

    # S3-compatible object storage (Cloudflare R2 recommended initially).
    s3_endpoint_url: str
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_bucket: str = "financial-intelligence"
    s3_region: str = "auto"

    max_download_mb: int = 50
    chunk_size_chars: int = 3500
    chunk_overlap_chars: int = 400

    # Reserved for a later grounded-generation layer.
    openai_api_key: str | None = None
    chat_model: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
