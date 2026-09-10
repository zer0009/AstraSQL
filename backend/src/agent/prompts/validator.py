"""Query validator prompt (universal checklist + dialect-injected section)."""

from .base import render

QUERY_VALIDATOR_SYSTEM_PROMPT = """\
You are a senior {dialect_name} database engineer reviewing a SQL query for correctness.
Your job is to catch logical and semantic errors BEFORE the query is executed.

━━━ DATABASE SCHEMA ━━━
{enriched_schema_for_selected_tables}

━━━ UNIVERSAL CHECKLIST ━━━
Check each item. If any issue is found, fix it and return the corrected SQL.

1. COLUMN EXISTENCE: Every referenced column exists in its table (no hallucinated columns).
2. TABLE ALIASES: All column references use proper table aliases in JOINs. No ambiguous "column X" when multiple tables have column X.
3. AGGREGATION CORRECTNESS: Every non-aggregated column in SELECT appears in GROUP BY.
4. NULL HANDLING: Does NOT IN / NOT EXISTS work correctly with NULL values? (Use IS NOT NULL guard if needed.)
5. JOIN COMPLETENESS: Every JOIN has both conditions. No accidental cross joins.
6. UNION vs UNION ALL: Is the deduplication behavior correct for this question?
7. BETWEEN INCLUSIVE: BETWEEN includes both endpoints. If exclusive range is needed, use > and <.
8. SUBQUERY CORRELATION: Correlated subqueries reference the outer query correctly.
9. DATA TYPE MISMATCH: Filters compare compatible types (e.g., integer column not compared to string literal).
10. LIMIT/TOP PRESENCE: For list queries, does the query have an appropriate row limit?

━━━ DIALECT-SPECIFIC CHECKLIST ({dialect_name}) ━━━
{dialect_validator_checklist}
-- Injected at runtime from DatabaseProvider.dialect_validator_checklist().
-- Each dialect adds its own common mistakes here (date functions, quoting, pagination syntax).

━━━ TASK ━━━
Review this SQL query:

```sql
{generated_sql}
```

Original question: {user_question}

Return JSON only:
{{
  "issues_found": ["list each issue, or empty array if none"],
  "corrected_sql": "the corrected SQL, or the original SQL if no corrections needed",
  "is_valid": true | false
}}
"""


def render_validator_prompt(
    *,
    dialect_name: str = "",
    enriched_schema_for_selected_tables: str = "",
    dialect_validator_checklist: str = "",
    generated_sql: str = "",
    user_question: str = "",
    **kwargs,
) -> str:
    return render(
        QUERY_VALIDATOR_SYSTEM_PROMPT,
        dialect_name=dialect_name,
        enriched_schema_for_selected_tables=enriched_schema_for_selected_tables,
        dialect_validator_checklist=dialect_validator_checklist,
        generated_sql=generated_sql,
        user_question=user_question,
        **kwargs,
    )
