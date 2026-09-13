"""Schema auto-enrichment prompt (background task, batch-aware)."""

from .base import render

SCHEMA_ENRICHMENT_PROMPT = """\
You are a database documentation specialist. Generate concise table and column \
descriptions for schema retrieval. Prefer short, high-signal text over verbose prose.

━━━ TABLES ━━━
{tables_block}

━━━ TASK ━━━
For EACH table above, produce:
1. table_description: ONE short sentence — business purpose + key relationships only.
2. columns: descriptions ONLY for non-obvious columns that help an analyst write SQL.
   Skip audit fields, raw primary keys, and foreign-key id columns (relationships are
   already visible in the DDL). Prefer 5–15 words per column when a description is needed.
   If a column looks like an enum, list known values from the sample rows.

Return JSON only, keyed by exact table name:
{{
  "table_name_1": {{
    "table_description": "...",
    "columns": {{"col_a": "...", "col_b": "..."}}
  }},
  "table_name_2": {{
    "table_description": "...",
    "columns": {{}}
  }}
}}
"""


def render_enrichment_prompt(
    create_table_statement: str = "",
    sample_rows: str = "",
    *,
    tables_block: str = "",
) -> str:
    """Render enrichment prompt.

    Prefer ``tables_block`` (multi-table). Legacy single-table args are still
    accepted and wrapped into a one-table block for compatibility.
    """
    block = (tables_block or "").strip()
    if not block:
        ddl = (create_table_statement or "").strip() or "(no schema)"
        samples = (sample_rows or "").strip() or "(no sample rows)"
        block = f"TABLE: (unknown)\n{ddl}\nSample rows:\n{samples}"
    return render(SCHEMA_ENRICHMENT_PROMPT, tables_block=block)


def format_enrichment_table_block(
    table_name: str,
    create_table_statement: str,
    sample_rows: str,
    *,
    index: int | None = None,
) -> str:
    """Format one table section for a batch enrichment prompt."""
    label = f"TABLE {index}: {table_name}" if index is not None else f"TABLE: {table_name}"
    ddl = (create_table_statement or "").strip() or f"CREATE TABLE {table_name} ();"
    samples = (sample_rows or "").strip() or "(no sample rows)"
    return f"{label}\n{ddl}\nSample rows:\n{samples}"
