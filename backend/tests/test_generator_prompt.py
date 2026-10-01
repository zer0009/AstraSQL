from src.agent.prompts.generator import (
    QUERY_GENERATOR_SYSTEM_PROMPT,
    render_generator_prompt,
)


def test_generator_prompt_contains_project_only():
    text = QUERY_GENERATOR_SYSTEM_PROMPT.lower()
    assert "project only" in text


def test_render_generator_prompt_keeps_project_only():
    rendered = render_generator_prompt(
        dialect_name="PostgreSQL",
        enriched_schema="CREATE TABLE t (id INT);",
        business_rules="(none)",
        golden_records="(none)",
        user_question="list ids",
    ).lower()
    assert "project only" in rendered
