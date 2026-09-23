from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[3]  # AstraSQL_V2/
_BACKEND = Path(__file__).resolve().parents[2]  # backend/

# Placeholder only — refused at startup when DEBUG=false.
DEFAULT_ENCRYPTION_KEY = "change-me-to-a-32-byte-secret!!"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_ROOT / ".env", _BACKEND / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AstraSQL"
    debug: bool = False
    data_dir: Path = Path("./data")
    sqlite_url: str = "sqlite+aiosqlite:///./data/astrasql.db"
    # Alias of SQLITE_URL so a later Postgres metadata URL is a config change.
    database_url: str = ""
    encryption_key: str = DEFAULT_ENCRYPTION_KEY

    # Auth (single local admin in this release)
    default_admin_username: str = "admin"
    default_admin_password: str = "AstraSQL-change-me"
    session_ttl_days: int = Field(default=7, ge=1, le=90)
    session_cookie_name: str = "astrasql_session"

    # LLM
    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 8192

    # Schema enrichment (cheaper/faster path than query generation)
    # Empty enrichment_model → use the provider's default chat model.
    enrichment_model: str = "gpt-4o-mini"
    enrichment_max_tokens: int = Field(default=1000, ge=256, le=8192)
    enrichment_batch_size: int = Field(default=8, ge=1, le=20)
    enrichment_concurrency: int = Field(default=6, ge=1, le=16)

    # Query
    max_result_rows: int = 500
    max_retries: int = 3
    max_conversation_turns: int = Field(default=3, ge=1, le=10)
    schema_cache_ttl_days: int = 7
    faiss_top_k_tables: int = 60
    golden_records_top_k: int = 5

    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def metadata_database_url(self) -> str:
        url = (self.database_url or "").strip()
        return url or self.sqlite_url

    @property
    def auth_cookie_secure(self) -> bool:
        return not self.debug

    @property
    def faiss_dir(self) -> Path:
        return self.data_dir / "faiss"

    @model_validator(mode="after")
    def reject_insecure_encryption_key(self) -> "Settings":
        key = (self.encryption_key or "").strip()
        if not self.debug and (not key or key == DEFAULT_ENCRYPTION_KEY):
            raise ValueError(
                "ENCRYPTION_KEY must be set to a unique non-default value when "
                "DEBUG=false. Copy .env.example to .env and set ENCRYPTION_KEY "
                "(e.g. python -c \"import secrets; print(secrets.token_urlsafe(32))\")."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
