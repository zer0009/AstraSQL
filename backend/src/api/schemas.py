from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

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
    name: Optional[str] = None
    db_type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    ssl_enabled: Optional[bool] = None


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
    last_scanned_at: Optional[datetime] = None
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
    current_table: Optional[str] = None
    tables_total: int = 0
    tables_done: int = 0
    tables_cached: list[str] = Field(default_factory=list)
    percent: int = 0
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_scanned_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Context — enrichments
# ---------------------------------------------------------------------------


class EnrichmentCreate(BaseModel):
    connection_id: str
    table_name: str
    column_name: Optional[str] = None
    description: Optional[str] = None
    alias: Optional[str] = None
    example_values: Optional[Any] = None


class EnrichmentUpdate(BaseModel):
    table_name: Optional[str] = None
    column_name: Optional[str] = None
    description: Optional[str] = None
    alias: Optional[str] = None
    example_values: Optional[Any] = None


class EnrichmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connection_id: str
    table_name: str
    column_name: Optional[str] = None
    description: Optional[str] = None
    alias: Optional[str] = None
    example_values: Optional[str] = None
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


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


class ConversationTurn(BaseModel):
    """One completed Q-SQL-Answer turn for multi-turn context."""

    question: str
    sql: Optional[str] = None
    answer: Optional[str] = None


class QueryRequest(BaseModel):
    connection_id: str
    question: str
    conversation_history: list[ConversationTurn] = Field(default_factory=list)
    session_id: Optional[str] = None


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

    question: Optional[str] = None
    sql: Optional[str] = None
    corrected_sql: Optional[str] = None
    columns: Optional[list[str]] = None
    rows: Optional[list[dict[str, Any]]] = None
    results: Optional[dict[str, Any]] = None
    answer: Optional[str] = None
    key_finding: Optional[str] = None
    confidence: Optional[Any] = None  # "HIGH"|"MEDIUM"|"LOW" or float
    explanation: Optional[str] = None
    follow_ups: Optional[list[str]] = None
    steps: Optional[list[dict[str, Any]]] = None
    error: Optional[str] = None
    retries: Optional[int] = None
    intent: Optional[str] = None
    history_id: Optional[str] = None
    connection_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Chat sessions
# ---------------------------------------------------------------------------


class SessionCreate(BaseModel):
    connection_id: str
    title: Optional[str] = None


class SessionRename(BaseModel):
    title: str


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connection_id: str
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connection_id: str
    session_id: Optional[str] = None
    turn_index: Optional[int] = None
    question: str
    sql: str
    result_row_count: Optional[int] = None
    confidence: Optional[float] = None
    user_rating: Optional[int] = None
    explanation: Optional[str] = None
    follow_ups: Optional[str] = None
    created_at: datetime


class SessionDetailOut(SessionOut):
    queries: list[HistoryOut] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    rating: Literal[1, -1]
    corrected_sql: Optional[str] = None


class FeedbackOut(BaseModel):
    id: str
    user_rating: int
    golden_record_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class ExportRequest(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any] | list[Any]]
    format: Literal["csv", "xlsx", "json"]
    filename: Optional[str] = None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class PublicSettingsOut(BaseModel):
    app_name: str
    llm_provider: str
    model: str
    max_rows: int
    database_types: list[str] = Field(default_factory=list)
