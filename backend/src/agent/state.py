from typing import Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    connection_id: str
    question: str
    intent: str
    intent_reason: str
    context: dict  # serializable RetrievedContext fields
    sql: str
    corrected_sql: str
    results: dict  # {columns, rows, row_count}
    retries: int
    retry_context: str
    error: Optional[str]
    confidence: str  # HIGH|MEDIUM|LOW
    answer: str
    key_finding: str
    assumption: Optional[str]
    follow_ups: list[str]
    steps: list[dict]  # agent step events for SSE
    # Prior completed turns for multi-turn follow-ups (working-memory window).
    conversation_history: list[dict]  # [{question, sql, answer}, ...]
    # Injected by runner (not from LLM):
    # session and connection are handled outside graph or via config
