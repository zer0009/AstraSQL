"""Agent prompt templates and render helpers."""

from .base import render
from .enrichment import SCHEMA_ENRICHMENT_PROMPT, render_enrichment_prompt
from .formatter import RESPONSE_FORMATTER_SYSTEM_PROMPT, render_formatter_prompt
from .generator import QUERY_GENERATOR_SYSTEM_PROMPT, render_generator_prompt
from .intent import (
    INTENT_SYSTEM_PROMPT,
    INTENT_USER_PROMPT,
    render_intent_prompt,
)
from .schema_link import (
    COLUMN_FIRST_PROMPT,
    TABLE_FIRST_PROMPT,
    render_column_first_prompt,
    render_table_first_prompt,
)
from .validator import QUERY_VALIDATOR_SYSTEM_PROMPT, render_validator_prompt

__all__ = [
    "render",
    "INTENT_SYSTEM_PROMPT",
    "INTENT_USER_PROMPT",
    "render_intent_prompt",
    "TABLE_FIRST_PROMPT",
    "COLUMN_FIRST_PROMPT",
    "render_table_first_prompt",
    "render_column_first_prompt",
    "QUERY_GENERATOR_SYSTEM_PROMPT",
    "render_generator_prompt",
    "QUERY_VALIDATOR_SYSTEM_PROMPT",
    "render_validator_prompt",
    "RESPONSE_FORMATTER_SYSTEM_PROMPT",
    "render_formatter_prompt",
    "SCHEMA_ENRICHMENT_PROMPT",
    "render_enrichment_prompt",
]
