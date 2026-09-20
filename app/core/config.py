from functools import lru_cache

from pydantic import field_validator, model_validator
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

    # S3-compatible object storage (Backblaze B2 in the validated deployment).
    s3_endpoint_url: str
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_bucket: str = "financial-intelligence"
    s3_region: str = "auto"

    max_download_mb: int = 50
    chunk_size_chars: int = 3500
    chunk_overlap_chars: int = 400

    # Existing operator identity. Both values are required before protected
    # routes become available; they must be supplied through deployment secrets.
    dashboard_username: str | None = None
    dashboard_password: str | None = None

    # Optional inspection-only identity. Leaving both unset preserves the current
    # single-operator behavior exactly. If enabled later, this identity may access
    # protected GET dashboard/API-v1 evidence surfaces but never operator-only
    # manual POST routes such as /ingest or /ask.
    dashboard_readonly_username: str | None = None
    dashboard_readonly_password: str | None = None

    # Phase 4 trust promotion is deliberately disabled by default. The code path
    # may be exercised in isolated tests, but live ingestion must not upgrade a
    # VERIFIED claim to TRUSTED until real dated primary + independent evidence
    # has been validated end-to-end.
    trust_promotion_enabled: bool = False

    # Phase 5 source monitoring also fails closed by default. Discovery and
    # automatic ingestion have independent gates: enabling feed observation must
    # never silently enable following/ingesting discovered links.
    source_monitoring_enabled: bool = False
    source_auto_ingest_enabled: bool = False
    monitor_supabase_max_mb: int | None = None
    monitor_b2_max_mb: int | None = None
    monitor_qdrant_max_points: int | None = None
    monitor_capacity_low_watermark_percent: int = 10

    # Reserved for a later grounded-generation layer.
    openai_api_key: str | None = None
    chat_model: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        """Use the installed psycopg v3 driver for plain PostgreSQL URLs.

        Supabase commonly provides connection strings beginning with
        ``postgresql://``. SQLAlchemy otherwise defaults that scheme to the
        legacy psycopg2 driver, while this project intentionally depends on
        psycopg v3. Normalizing here keeps copied Supabase URLs working without
        requiring users to edit credentials manually.
        """
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator(
        "monitor_supabase_max_mb",
        "monitor_b2_max_mb",
        "monitor_qdrant_max_points",
    )
    @classmethod
    def positive_optional_monitor_budget(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("monitor capacity ceilings must be positive")
        return value

    @field_validator("monitor_capacity_low_watermark_percent")
    @classmethod
    def valid_monitor_low_watermark(cls, value: int) -> int:
        if not 1 <= value <= 50:
            raise ValueError("monitor capacity low watermark must be between 1 and 50")
        return value

    @model_validator(mode="after")
    def complete_optional_readonly_credentials(self) -> "Settings":
        username_set = bool((self.dashboard_readonly_username or "").strip())
        password_set = bool((self.dashboard_readonly_password or "").strip())
        if username_set != password_set:
            raise ValueError(
                "dashboard read-only username/password must be configured together"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
