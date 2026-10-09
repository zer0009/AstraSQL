from typing import TypedDict


class AgentState(TypedDict, total=False):
    connection_id: str
    question: str
    intent: str
    intent_reason: str
    context: dict  # serializable RetrievedContext fields (+ schema_digest)
    sql: str
    corrected_sql: str
    results: dict  # {columns, rows, row_count}
    # When True, query_executor should skip re-running the chosen SQL.
    cached_execution: bool
    retries: int
    retry_context: str
    # Soft post-execute retry (e.g. EMPTY_RESULT). Not a hard execution error.
    shape_retry: bool
    error: str | None
    confidence: str  # HIGH|MEDIUM|LOW
    trust_level: str  # certified|taught|guessed|clarifying|failed
    answer: str
    key_finding: str
    assumption: str | None
    follow_ups: list[str]
    clarification_options: list[str]
    used_golden: bool
    # {should_clarify, reason, options, status?, decision_why?, assumption?}
    ambiguity: dict
    steps: list[dict]  # agent step events for SSE
    # Prior completed turns for multi-turn follow-ups (working-memory window).
    # Optional trust_level helps clarification budget detection.
    conversation_history: list[dict]  # [{question, sql, answer, trust_level?}, ...]
    # Optional external knowledge (BIRD evidence, customer data dictionary notes).
    evidence: str
    # Refine / resume: when False, never ask again; skip retrieval when context set.
    allow_clarify: bool
    run_id: str
    refine_choice: str
    # Injected by runner (not from LLM):
    # session and connection are handled outside graph or via config
