from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[3]  # AstraSQL_V2/
_BACKEND = Path(__file__).resolve().parents[2]  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_ROOT / ".env", _BACKEND / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AstraSQL V2"
    debug: bool = False
    data_dir: Path = Path("./data")
    sqlite_url: str = "sqlite+aiosqlite:///./data/astrasql.db"
    encryption_key: str = "change-me-to-a-32-byte-secret!!"

    # LLM
    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 8192

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
    def faiss_dir(self) -> Path:
        return self.data_dir / "faiss"


@lru_cache
def get_settings() -> Settings:
    return Settings()
