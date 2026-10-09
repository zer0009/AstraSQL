from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


class ConnectionCreate(BaseModel):
    name: str
    db_type: str
    host: str
    port: int
    database: str
    username: str
    password: str
    ssl_enabled: bool = False


class ConnectionUpdate(BaseModel):
    name: str | None = None
    db_type: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None
    ssl_enabled: bool | None = None


class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    db_type: str
    host: str
    port: int
    database: str
    username: str
    password_set: bool = True
    ssl_enabled: bool
    last_scanned_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str


class ConnectionScanResult(BaseModel):
    """Immediate ack when a background scan is started."""

    job_id: str
    connection_id: str
    status: str
    message: str


class ScanJobStatus(BaseModel):
    job_id: str
    connection_id: str
    connection_name: str
    status: str
    phase: str
    message: str
    current_table: str | None = None
    tables_total: int = 0
    tables_done: int = 0
    tables_cached: list[str] = Field(default_factory=list)
    percent: int = 0
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    last_scanned_at: str | None = None


# ---------------------------------------------------------------------------
# Context — enrichments
# ---------------------------------------------------------------------------


class EnrichmentCreate(BaseModel):
    connection_id: str
    table_name: str
    column_name: str | None = None
    description: str | None = None
    alias: str | None = None
    example_values: Any | None = None


class EnrichmentUpdate(BaseModel):
    table_name: str | None = None
    column_name: str | None = None
    description: str | None = None
    alias: str | None = None
    example_values: Any | None = None


class EnrichmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connection_id: str
    table_name: str
    column_name: str | None = None
    description: str | None = None
    alias: str | None = None
    example_values: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Context — golden records
# ---------------------------------------------------------------------------


class GoldenRecordCreate(BaseModel):
    connection_id: str
    question: str
    sql: str


class GoldenRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connection_id: str
    question: str
    sql: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Context — business rules
# ---------------------------------------------------------------------------


class BusinessRuleCreate(BaseModel):
    connection_id: str
    content: str


class BusinessRuleUpdate(BaseModel):
    content: str


class BusinessRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connection_id: str
    content: str
    created_at: datetime
    updated_at: datetime


class ContextPackDocument(BaseModel):
    version: int = 1
    enrichments: list[dict[str, Any]] = Field(default_factory=list)
    rules: list[dict[str, Any]] = Field(default_factory=list)
    goldens: list[dict[str, Any]] = Field(default_factory=list)


class ContextPackImport(BaseModel):
    connection_id: str
    pack: ContextPackDocument


class ContextPackImportResult(BaseModel):
    enrichments: int
    rules: int
    goldens: int


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


class ConversationTurn(BaseModel):
    """One completed Q-SQL-Answer turn for multi-turn context."""

    question: str
    sql: str | None = None
    answer: str | None = None
    trust_level: str | None = None


class QueryRequest(BaseModel):
    connection_id: str
    question: str
    conversation_history: list[ConversationTurn] = Field(default_factory=list)
    session_id: str | None = None
    # Optional schema/business hint (BIRD-style evidence / glossary snippet).
    evidence: str | None = None


class RefineRequest(BaseModel):
    """Resume a prior run with a chosen interpretation (no full re-retrieval)."""

    run_id: str
    choice: str
    connection_id: str | None = None
    session_id: str | None = None


class RememberDefinitionRequest(BaseModel):
    """Promote a chosen reading into a durable business rule."""

    connection_id: str
    definition: str
    term: str | None = None


class ExecuteSqlRequest(BaseModel):
    """Re-run a previously generated SQL statement with no LLM involvement."""

    connection_id: str
    sql: str


class ExecuteSqlOut(BaseModel):
    sql: str
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0


class AgentStateOut(BaseModel):
    """Flexible agent result; extra fields from the runner are preserved."""

    model_config = ConfigDict(extra="allow")

    question: str | None = None
    sql: str | None = None
    corrected_sql: str | None = None
    columns: list[str] | None = None
    rows: list[dict[str, Any]] | None = None
    results: dict[str, Any] | None = None
    answer: str | None = None
    key_finding: str | None = None
    assumption: str | None = None
    confidence: Any | None = None  # "HIGH"|"MEDIUM"|"LOW" or float
    trust_level: str | None = None
    explanation: str | None = None
    follow_ups: list[str] | None = None
    steps: list[dict[str, Any]] | None = None
    error: str | None = None
    retries: int | None = None
    intent: str | None = None
    history_id: str | None = None
    connection_id: str | None = None


# ---------------------------------------------------------------------------
# Chat sessions
# ---------------------------------------------------------------------------


class SessionCreate(BaseModel):
    connection_id: str
    title: str | None = None


class SessionRename(BaseModel):
    title: str


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connection_id: str
    title: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connection_id: str
    session_id: str | None = None
    turn_index: int | None = None
    question: str
    sql: str
    result_row_count: int | None = None
    confidence: float | None = None
    trust_level: str | None = None
    user_rating: int | None = None
    explanation: str | None = None
    follow_ups: str | None = None
    ambiguity_json: str | None = None
    created_at: datetime


class SessionDetailOut(SessionOut):
    queries: list[HistoryOut] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    rating: Literal[1, -1]
    corrected_sql: str | None = None
    new_rule: str | None = None


class FeedbackOut(BaseModel):
    id: str
    user_rating: int
    golden_record_id: str | None = None
    rule_id: str | None = None


class HistoryStatsOut(BaseModel):
    total: int = 0
    high_confidence: int = 0
    medium_confidence: int = 0
    low_confidence: int = 0
    unknown_confidence: int = 0
    error_count: int = 0
    negative_rated: int = 0
    positive_rated: int = 0
    unrated: int = 0


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class ExportRequest(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any] | list[Any]]
    format: Literal["csv", "xlsx", "json"]
    filename: str | None = None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AuthUserOut(BaseModel):
    id: str
    username: str
    is_admin: bool
    must_change_password: bool


class AuthStatusOut(BaseModel):
    setup_complete: bool


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class PublicSettingsOut(BaseModel):
    app_name: str
    llm_provider: str
    model: str
    max_rows: int
    database_types: list[str] = Field(default_factory=list)
    # Behavior flags (read-only; set via env).
    execution_evidence_gate: bool = True
    merge_interpret_generate: bool = True
    ambiguity_policy: str = "balanced"
    relationship_discovery_enabled: bool = True
    relationship_auto_approve: bool = True
    learning_loop_enabled: bool = True
    sse_row_preview_limit: int = 100


# ---------------------------------------------------------------------------
# Semantic layer / relationships / dictionary
# ---------------------------------------------------------------------------


class SemanticRelationshipOut(BaseModel):
    from_table: str
    from_col: str
    to_table: str
    to_col: str
    status: str = "proposed"
    score: float | None = None
    evidence: str | None = None


class SemanticLayerOut(BaseModel):
    connection_id: str
    relationships: list[SemanticRelationshipOut] = Field(default_factory=list)
    conventions: list[str] = Field(default_factory=list)
    reviewed_queries: list[dict[str, Any]] = Field(default_factory=list)
    repair_memory: list[dict[str, Any]] = Field(default_factory=list)
    join_paths: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class RelationshipStatusUpdate(BaseModel):
    status: Literal["approved", "proposed", "rejected"]


class DictionaryImportRequest(BaseModel):
    """Import a data dictionary into schema enrichments.

    Provide either ``content`` (inline JSON/CSV text) or ``format`` hints.
    For file uploads use multipart endpoint separately.
    """

    format: Literal["json", "csv", "bird_csv"] = "json"
    content: str
    table_name: str | None = None  # required for single-table bird_csv


class DictionaryImportOut(BaseModel):
    enrichments_created: int = 0
    enrichments_updated: int = 0
    rows_parsed: int = 0
    message: str = ""


class AgentGraphOut(BaseModel):
    mermaid: str
    nodes: list[str] = Field(default_factory=list)
    merge_interpret_generate: bool = True
    execution_evidence_gate: bool = True
