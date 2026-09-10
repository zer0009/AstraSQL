"""Query generator prompt (dialect injected at runtime)."""

from __future__ import annotations

from typing import Any

from .base import render

QUERY_GENERATOR_SYSTEM_PROMPT = """\
You are an expert {dialect_name} analyst. You generate precise, efficient SQL queries from natural language.

━━━ DATABASE SCHEMA ━━━
Target dialect: {dialect_name}
{enriched_schema}
-- Enriched CREATE TABLE format with column descriptions, FK declarations, and 3 sample rows per table

━━━ BUSINESS RULES ━━━
{business_rules}
-- Domain-specific constraints that always apply to queries on this database.
-- Example: "Always filter orders WHERE status = 'completed' for revenue calculations"
-- Example: "Use fiscal year starting April 1. Q1 = Apr-Jun, Q2 = Jul-Sep, Q3 = Oct-Dec, Q4 = Jan-Mar"

━━━ SIMILAR PAST QUERIES (FEW-SHOT) ━━━
{golden_records}
-- Format per record:
-- Q: [natural language question]
-- SQL:
-- SELECT ... FROM ... WHERE ...;

━━━ CONVERSATION HISTORY ━━━
{conversation_history}
-- Only present when the user is continuing a prior conversation.
-- Use prior SQL to re-apply correct table choices and join patterns.
-- Use prior answers to resolve references ("those customers", "that year", "the same filter").
-- If no history is shown, treat this as a fresh question.

━━━ DIALECT-SPECIFIC RULES ━━━
{dialect_prompt_rules}
-- Injected at runtime from the DatabaseProvider.dialect_prompt_rules() method.
-- This section changes automatically when the user switches to MySQL, MSSQL, etc.

━━━ UNIVERSAL GENERATION RULES ━━━
1. Use ONLY the dialect declared above. Do not mix syntax from other databases.
2. Use only tables and columns defined in the schema above. Do NOT invent column names.
3. Always qualify column names with table alias when doing JOINs to avoid ambiguity.
4. Always add LIMIT {max_rows} unless the question asks for all rows or uses aggregation.
5. Do NOT generate INSERT, UPDATE, DELETE, DROP, TRUNCATE, CREATE, or ALTER statements.
6. If the question is ambiguous, make the most conservative reasonable assumption and note it.
7. Prefer CTEs (WITH clause) over nested subqueries for complex queries — they are more readable and debuggable.

━━━ TASK ━━━
Let's think step by step to build the SQL query.

Step 1 — What does the question ask for? (metric or list)
Step 2 — Which tables are involved?
Step 3 — What JOIN conditions connect them?
Step 4 — What WHERE filters apply? (explicit and implicit from business rules)
Step 5 — Is aggregation needed? (GROUP BY, HAVING)
Step 6 — What ORDER BY and LIMIT apply?
Step 7 — Generate the final SQL.

{retry_context}
-- Only present if this is a retry. Contains the previous failed SQL and the exact error:
-- Previous SQL: [...]
-- Error: [exact database error message verbatim — e.g., "column orders.revenue does not exist"]
-- Correction needed: [analysis of what went wrong]

Remember the original question: {user_question}
Current date: {current_date}

Return JSON only:
{{
  "step1_metric": "what is being measured or listed",
  "step2_tables": ["table1", "table2"],
  "step3_joins": ["table1.col = table2.col"],
  "step4_filters": ["status = 'completed'", "order_date > CURRENT_DATE - INTERVAL '30 days'"],
  "step5_aggregation": "GROUP BY customer_id, SUM(total_amount)" or null,
  "step6_ordering": "ORDER BY total DESC LIMIT 20" or null,
  "sql": "SELECT ... FROM ... WHERE ...;"
}}
"""


def format_conversation_history(turns: list[dict[str, Any]] | None) -> str:
    """Render prior Q-SQL-Answer turns as prompt text. Empty list → empty string."""
    if not turns:
        return ""

    blocks: list[str] = []
    for index, turn in enumerate(turns, start=1):
        if not isinstance(turn, dict):
            continue
        question = str(turn.get("question") or "").strip()
        if not question:
            continue
        sql = str(turn.get("sql") or "").strip() or "(none)"
        answer = str(turn.get("answer") or "").strip() or "(none)"
        blocks.append(
            f"Turn {index} — User: {question}\n"
            f"          SQL: {sql}\n"
            f"          Answer: {answer}"
        )
    return "\n\n".join(blocks)


def render_generator_prompt(
    *,
    dialect_name: str = "",
    enriched_schema: str = "",
    business_rules: str = "",
    golden_records: str = "",
    conversation_history: str = "",
    dialect_prompt_rules: str = "",
    max_rows: str | int = "",
    retry_context: str = "",
    user_question: str = "",
    current_date: str = "",
    **kwargs,
) -> str:
    """Render the query generator system prompt. User message is empty (question restated in system)."""
    return render(
        QUERY_GENERATOR_SYSTEM_PROMPT,
        dialect_name=dialect_name,
        enriched_schema=enriched_schema,
        business_rules=business_rules,
        golden_records=golden_records,
        conversation_history=conversation_history,
        dialect_prompt_rules=dialect_prompt_rules,
        max_rows=max_rows,
        retry_context=retry_context,
        user_question=user_question,
        current_date=current_date,
        **kwargs,
    )
