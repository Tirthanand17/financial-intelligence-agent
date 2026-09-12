from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    database_url: str
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "financial_knowledge"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str = "financial-intelligence"
    minio_secure: bool = False

    openai_api_key: str | None = None
    embedding_model: str | None = None
    chat_model: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
