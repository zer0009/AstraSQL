"""Two-stage bidirectional schema linker prompts (dialect-agnostic)."""

from .base import render

TABLE_FIRST_PROMPT = """\
You are a database schema analyst.
Your task: identify which tables are needed to answer the user's question.

Available tables (names and short descriptions only):
{table_catalog}
-- Format: table_name: one-line description
-- Example:
-- orders: purchase transactions with customer, amount, status
-- customers: customer profile and contact information

Rules:
- Select the minimum set of tables necessary and sufficient to answer the question.
- Include tables needed for JOINs even if not directly mentioned.
- If unsure between two tables, include both.
- Think step by step before answering.

Return JSON only:
{{
  "reasoning": "step by step analysis of what the question needs",
  "selected_tables": ["table1", "table2"]
}}
"""

TABLE_FIRST_USER_PROMPT = """\
Question: {user_question}
Current date: {current_date}
"""

COLUMN_FIRST_PROMPT = """\
You are a database schema analyst.
Your task: identify which specific columns are most relevant to the user's question, then derive their tables.

Full schema (all tables and columns):
{compact_schema}
-- Format: table.column (type) [description if available]

Rules:
- Identify columns for: SELECT projection, WHERE filters, JOIN keys, GROUP BY dimensions, ORDER BY fields.
- Think about what the question is measuring and what constraints it implies.

Return JSON only:
{{
  "reasoning": "what the question measures, what filters it needs, what groupings",
  "selected_columns": [
    {{"table": "orders", "column": "total_amount"}},
    {{"table": "orders", "column": "status"}},
    {{"table": "customers", "column": "name"}}
  ]
}}
"""

COLUMN_FIRST_USER_PROMPT = """\
Question: {user_question}
Current date: {current_date}
"""


def render_table_first_prompt(
    user_question: str,
    table_catalog: str,
    current_date: str,
) -> tuple[str, str]:
    system = render(TABLE_FIRST_PROMPT, table_catalog=table_catalog)
    user = render(
        TABLE_FIRST_USER_PROMPT,
        user_question=user_question,
        current_date=current_date,
    )
    return system, user


def render_column_first_prompt(
    user_question: str,
    compact_schema: str,
    current_date: str,
) -> tuple[str, str]:
    system = render(COLUMN_FIRST_PROMPT, compact_schema=compact_schema)
    user = render(
        COLUMN_FIRST_USER_PROMPT,
        user_question=user_question,
        current_date=current_date,
    )
    return system, user
