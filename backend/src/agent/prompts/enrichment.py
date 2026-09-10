"""Schema auto-enrichment prompt (background task)."""

from .base import render

SCHEMA_ENRICHMENT_PROMPT = """\
You are a database documentation specialist. Given a table schema, generate clear, concise documentation for data analysts.

━━━ TABLE SCHEMA ━━━
{create_table_statement}

━━━ SAMPLE DATA ━━━
{sample_rows}

━━━ TASK ━━━
Generate a description for this table and each of its columns.

Rules:
1. Table description: 1 sentence explaining what this table stores and its business purpose.
2. Column descriptions: 1 sentence per column. Be specific about:
   - What the value represents (not just the column name restated)
   - Units (if numeric — e.g., "in cents", "in seconds", "USD")
   - Value format (for dates: "ISO 8601 timestamp", for codes: explain values)
   - Business meaning (e.g., "status = 'completed' means payment was received")
3. If a column appears to be an enum, list the known values from the sample rows.
4. If a column appears to be a foreign key, note the relationship.

Return JSON only:
{{
  "table_description": "...",
  "columns": {{
    "column_name": "description",
    "column_name_2": "description"
  }}
}}
"""


def render_enrichment_prompt(create_table_statement: str, sample_rows: str) -> str:
    return render(
        SCHEMA_ENRICHMENT_PROMPT,
        create_table_statement=create_table_statement,
        sample_rows=sample_rows,
    )
