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
-- Join conventions (INNER vs LEFT for "for each" / completeness) come from BUSINESS RULES
-- in context when present — follow those rules rather than inventing join policy.

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

━━━ RESOLVED INTERPRETATION ━━━
{interpretation_assumption}
-- When present, treat this as the chosen reading of any vague term in the question.
-- Do not re-ask the user. Do not invent a different metric.
-- If this section says "(none)", interpret the question normally from the schema.

━━━ DIALECT-SPECIFIC RULES ━━━
{dialect_prompt_rules}
-- Injected at runtime from the DatabaseProvider.dialect_prompt_rules() method.
-- This section changes automatically when the user switches to MySQL, MSSQL, etc.

━━━ UNIVERSAL GENERATION RULES ━━━
1. Use ONLY the dialect declared above. Do not mix syntax from other databases.
2. Use only tables and columns defined in the schema above. Do NOT invent column names.
3. Always qualify column names with table alias when doing JOINs to avoid ambiguity.
4. Row cap: the runtime enforces a maximum result-row limit. Do NOT add LIMIT solely for safety.
   Add LIMIT (or dialect equivalent) only when the question asks for top-N / first-N / a ranked slice.
5. Do NOT generate INSERT, UPDATE, DELETE, DROP, TRUNCATE, CREATE, or ALTER statements.
6. If a required filter value is not in the question, conversation history, or a business rule, omit that identity filter or write the query for every matching row. Do not invent a literal or a bind placeholder.
6b. This runner binds no parameters and maps no login to a database row.
7. Prefer CTEs (WITH clause) over nested subqueries for complex queries — they are more readable and debuggable.
8. PROJECT ONLY the columns the question asks for. Do not add helpful extra columns (counts, ids, timestamps, etc.) unless the question asks for names/labels of IDs or otherwise needs them to answer.
9. For "most" / "top" / "largest" / "highest" without an explicit request for "all ties": use ORDER BY … LIMIT 1 (or dialect equivalent). Do not use MAX/MIN in a way that returns every tied row unless the question asks for all ties.
10. HUMAN-READABLE RESULTS: When the question references named entities (states, countries, categories, products, vendors, customers) and asks for names/labels, JOIN the lookup/reference table and SELECT its name or display_name column alongside or instead of the raw *_id. If the question only asks for an id or a metric, do not expand to extra label columns. If the schema contains a lookup/reference table for a dimension (identifiable by having a name, title, label, code, or display_name column and being referenced by FK from fact tables), JOIN it when the question needs the dimension name — never group by the raw FK ID as a substitute for the dimension name when a name was requested.

━━━ TASK ━━━
Let's think step by step to build the SQL query.

Step 0 — Entity Disambiguation: For every named entity in the question, identify its dedicated lookup table in the schema above. Prefer a table whose columns include "name", "title", "label", "code", or "display_name" over a raw *_id column on a fact table. If the schema does not contain a suitable lookup table for an entity the question requires, state that explicitly in step2_tables instead of substituting a different column.
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
  "step0_entities": ["entity → lookup_table or missing"],
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


MERGED_GENERATOR_SYSTEM_PROMPT = """\
You are an expert {dialect_name} analyst. You interpret the question AND generate SQL in one step.

━━━ DATABASE SCHEMA ━━━
Target dialect: {dialect_name}
{enriched_schema}

━━━ SCHEMA DIGEST (compact) ━━━
{schema_digest}

━━━ BUSINESS RULES ━━━
{business_rules}

━━━ SIMILAR PAST QUERIES (FEW-SHOT) ━━━
{golden_records}

━━━ CONVERSATION HISTORY ━━━
{conversation_history}

━━━ DIALECT-SPECIFIC RULES ━━━
{dialect_prompt_rules}

━━━ UNIVERSAL RULES ━━━
1. Use ONLY the dialect declared above.
2. Use only tables/columns in the schema. Do not invent names.
3. Do NOT generate INSERT/UPDATE/DELETE/DDL.
4. PROJECT ONLY columns the question asks for.
5. Prefer CTEs for complex queries.
6. Flag decision_points ONLY when the question is genuinely underspecified
   (missing formula, vague entity, or multiple schema-grounded readings that
   would change the answer). Do NOT invent ambiguity for clear questions.

{retry_context}

Remember the original question: {user_question}
Current date: {current_date}

Return JSON only:
{{
  "status": "clear" | "assumed" | "ambiguous" | "unanswerable",
  "interpretation": "one-sentence reading of the question",
  "assumptions": ["assumption if any"],
  "decision_points": [
    {{"level": "intent"|"implementation", "description": "what is underspecified"}}
  ],
  "step1_metric": "what is being measured or listed",
  "step2_tables": ["table1"],
  "sql": "SELECT ...;"
}}
"""


def render_generator_prompt(
    *,
    dialect_name: str = "",
    enriched_schema: str = "",
    business_rules: str = "",
    golden_records: str = "",
    conversation_history: str = "",
    interpretation_assumption: str = "",
    dialect_prompt_rules: str = "",
    max_rows: str | int = "",
    retry_context: str = "",
    user_question: str = "",
    current_date: str = "",
    **kwargs,
) -> str:
    """Render the query generator system prompt.

    Static prefix (system role + dialect + schema + rules) comes before the
    dynamic question/date so OpenAI prompt caching can reuse the shared prefix.
    """
    assumption = (interpretation_assumption or "").strip() or "(none)"
    return render(
        QUERY_GENERATOR_SYSTEM_PROMPT,
        dialect_name=dialect_name,
        enriched_schema=enriched_schema,
        business_rules=business_rules,
        golden_records=golden_records,
        conversation_history=conversation_history,
        interpretation_assumption=assumption,
        dialect_prompt_rules=dialect_prompt_rules,
        max_rows=max_rows,
        retry_context=retry_context,
        user_question=user_question,
        current_date=current_date,
        **kwargs,
    )


def render_merged_generator_prompt(
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
    schema_digest: str = "",
    **kwargs,
) -> str:
    """Render interpret+generate merged system prompt (skips separate resolver)."""
    return render(
        MERGED_GENERATOR_SYSTEM_PROMPT,
        dialect_name=dialect_name,
        enriched_schema=enriched_schema,
        business_rules=business_rules or "(none)",
        golden_records=golden_records or "(none)",
        conversation_history=conversation_history or "(none)",
        dialect_prompt_rules=dialect_prompt_rules or "(none)",
        max_rows=max_rows,
        retry_context=retry_context or "",
        user_question=user_question,
        current_date=current_date,
        schema_digest=schema_digest or "(none)",
        **kwargs,
    )
