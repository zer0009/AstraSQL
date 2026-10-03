from src.agent.prompts.generator import (
    MERGED_GENERATOR_SYSTEM_PROMPT,
    QUERY_GENERATOR_SYSTEM_PROMPT,
    render_generator_prompt,
    render_merged_generator_prompt,
)


def test_generator_prompt_contains_project_only():
    text = QUERY_GENERATOR_SYSTEM_PROMPT.lower()
    assert "project only" in text
    assert "human-readable dimensions" in text


def test_merged_generator_requires_readable_dimensions():
    text = MERGED_GENERATOR_SYSTEM_PROMPT.lower()
    assert "human-readable dimensions" in text
    assert "raw id" in text or "raw ids" in text


def test_render_generator_prompt_keeps_project_only():
    rendered = render_generator_prompt(
        dialect_name="PostgreSQL",
        enriched_schema="CREATE TABLE t (id INT);",
        business_rules="(none)",
        golden_records="(none)",
        user_question="list ids",
    ).lower()
    assert "project only" in rendered
    assert "human-readable dimensions" in rendered


def test_render_merged_includes_readable_rule():
    rendered = render_merged_generator_prompt(
        dialect_name="PostgreSQL",
        enriched_schema="CREATE TABLE t (id INT);",
        user_question="sales by country",
    ).lower()
    assert "human-readable dimensions" in rendered
