from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
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
        populate_by_name=True,
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

    # LLM (primary fields; OPENAI_* env aliases kept for compatibility)
    llm_provider: str = "openai"
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY", "llm_api_key"),
    )
    llm_model: str = Field(
        default="gpt-4o",
        validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL", "llm_model"),
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias=AliasChoices(
            "EMBEDDING_MODEL", "OPENAI_EMBEDDING_MODEL", "embedding_model"
        ),
    )
    llm_temperature: float = 0.0
    llm_max_tokens: int = 8192
    # Reasoning models (gpt-5.*): none|low|medium|high|xhigh ("minimal" → none).
    # Default low — empty previously meant provider default (often high) and burned tokens.
    llm_reasoning_effort: str = "low"
    # Per-stage effort overrides (empty → stage defaults / llm_reasoning_effort).
    intent_reasoning_effort: str = "none"
    formatter_reasoning_effort: str = "none"
    expansion_reasoning_effort: str = "none"
    generator_reasoning_effort: str = ""
    repair_reasoning_effort: str = "medium"
    # Per-stage max_tokens caps (0 → llm_max_tokens).
    intent_max_tokens: int = Field(default=256, ge=0, le=8192)
    formatter_max_tokens: int = Field(default=1024, ge=0, le=8192)
    expansion_max_tokens: int = Field(default=256, ge=0, le=8192)
    generator_max_tokens: int = Field(default=4096, ge=0, le=16384)
    validator_max_tokens: int = Field(default=2048, ge=0, le=8192)
    direct_max_tokens: int = Field(default=1024, ge=0, le=8192)

    # Schema enrichment (cheaper/faster path than query generation)
    # Empty enrichment_model → use the provider's default chat model.
    enrichment_model: str = ""
    enrichment_max_tokens: int = Field(default=1000, ge=256, le=8192)
    enrichment_batch_size: int = Field(default=8, ge=1, le=20)
    enrichment_concurrency: int = Field(default=6, ge=1, le=16)

    # Query
    max_result_rows: int = 500
    max_retries: int = 3
    max_conversation_turns: int = Field(default=2, ge=1, le=10)
    schema_cache_ttl_days: int = 7
    faiss_top_k_tables: int = 60
    golden_records_top_k: int = 5
    # Minimum FAISS inner-product score to inject a golden few-shot (0 = always top-k).
    golden_min_score: float = Field(default=0.45, ge=0.0, le=1.0)
    # Verified-cache embedding similarity to skip generation entirely.
    verified_min_score: float = Field(default=0.92, ge=0.5, le=1.0)
    # Sample rows included in schema prompts (0 = none).
    schema_sample_rows: int = Field(default=2, ge=0, le=5)
    # Skip expansion LLM for schema linking (use question + history only).
    schema_link_expand: bool = False
    # Use a single LLM select call (table-first) instead of parallel table+column.
    schema_link_single_select: bool = True

    # Schema-grounded clarification (ask vs proceed after context retrieval)
    grounded_clarification_enabled: bool = True
    # Empty → use enrichment_model if set, else the provider default chat model.
    interpretation_model: str = ""

    # Ablation / performance switches (Phase 0+). Modes:
    # interpretation: on | off | assume_only  (assume_only = never ask, always proceed)
    # validator: full | deterministic | off
    # schema_link: auto | full | faiss  (auto = full schema when under token budget)
    # format_response: on | off  (off skips NL formatter — API/eval mode)
    interpretation_mode: str = "on"
    # Deterministic+EXPLAIN by default; LLM validator only when flags fire.
    validator_mode: str = "deterministic"
    schema_link_mode: str = "auto"
    format_response: bool = True
    # Stream tabular/SQL result before the NL formatter finishes.
    format_response_async: bool = True
    # Max candidates for adaptive multi-path generation (1 = disabled).
    sql_candidate_count: int = Field(default=1, ge=1, le=5)
    # Approximate token budget for "pass full schema" path (schema_link_mode=auto).
    schema_full_token_budget: int = Field(default=6000, ge=500, le=100000)
    # Distinct-value sample size for low-cardinality columns (value grounding).
    value_grounding_max_distinct: int = Field(default=50, ge=0, le=500)
    # Statement timeout seconds for read-only execute (0 = provider default).
    query_timeout_seconds: float = Field(default=30.0, ge=0.0, le=600.0)
    # Per-stage model overrides (empty → llm_model / enrichment_model).
    intent_model: str = ""
    formatter_model: str = ""
    expansion_model: str = ""

    # Execution-evidence ambiguity gate (Phase 1).
    # When true, ask only when sampled SQLs form split result clusters.
    # interpretation_mode still controls the old resolver for A/B:
    #   on = resolver then optional execution gate
    #   off = skip resolver; merged generate-with-interpretation when merge_interpret_generate
    #   assume_only = never ask
    execution_evidence_gate: bool = True
    # Answer-first: stream a result with assumption; alternatives arrive as chips.
    # Strict ambiguity_policy still asks when clusters split.
    answer_first: bool = True
    # Merge interpretation into the generator (skip intent + resolver LLM calls).
    # Measured: same/better values accuracy, lower p50/cost on held-out Spider.
    merge_interpret_generate: bool = True
    # Always use the merged generator output schema (status/decision_points).
    # Difficulty router only controls candidate count / model tier, not format.
    always_merged_schema: bool = True
    # Candidates to sample when decision_points are flagged (or gate always samples).
    # Adaptive gate starts at min(2, this) and escalates only on disagreement.
    ambiguity_sample_count: int = Field(default=3, ge=1, le=5)
    # Fraction of successful executes that must share one denotation to answer.
    # Below this (and ≥2 clusters) → ask. Casual connections can raise this.
    ambiguity_dominance_threshold: float = Field(default=0.67, ge=0.5, le=1.0)
    # Per-connection policy hint when no connection override: casual | balanced | strict.
    # strict asks more readily (lower dominance); casual answers more (higher).
    ambiguity_policy: str = "balanced"
    # Bounded repair agent (tool loop) after execution evidence fails.
    repair_agent_enabled: bool = True
    repair_max_steps: int = Field(default=3, ge=1, le=6)
    repair_max_cost_usd: float = Field(default=0.05, ge=0.0, le=5.0)
    # Empty-result: probe WHERE literals before regenerating.
    empty_result_literal_probe: bool = True
    # Estimated query cost gate: refuse/flag when EXPLAIN cost exceeds this (0 = off).
    explain_cost_limit: float = Field(default=0.0, ge=0.0, le=1e12)
    # Relationship discovery on schema scan (proposed join edges).
    relationship_discovery_enabled: bool = True
    # Auto-approve discovered relationships (solo-user default). Org can set false.
    relationship_auto_approve: bool = True
    # Column-level hybrid retrieval when table count exceeds this.
    large_schema_table_threshold: int = Field(default=40, ge=10, le=5000)
    # Enable bounded column-exploration tool during repair.
    column_exploration_enabled: bool = True
    # Deterministic sqlglot repairs after syntax validation (SQLite only).
    deterministic_sql_repair: bool = True
    # Governed learning: promote thumbs-up / edited SQL to reviewed queries.
    learning_loop_enabled: bool = True
    # Run intent classifier and context retrieval in parallel from START.
    # Off by default: both nodes write LastValue keys (error/steps); enable only
    # after AgentState uses Annotated reducers for concurrent updates.
    parallel_intent_retrieval: bool = False

    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def openai_api_key(self) -> str:
        """Deprecated alias for ``llm_api_key``."""
        return self.llm_api_key

    @property
    def openai_model(self) -> str:
        """Deprecated alias for ``llm_model``."""
        return self.llm_model

    @property
    def openai_embedding_model(self) -> str:
        """Deprecated alias for ``embedding_model``."""
        return self.embedding_model

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


def clear_settings_cache() -> None:
    """Drop the cached Settings instance (tests / eval model overrides)."""
    get_settings.cache_clear()


def override_settings_env(**env: str) -> None:
    """Set process env vars and clear the settings cache."""
    import os

    for key, value in env.items():
        os.environ[key] = value
    clear_settings_cache()
