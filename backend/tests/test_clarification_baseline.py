"""Regression fixture for schema-blind clarification (pre-fix baseline).

User report: "how we can calculate to get best employee" was classified
CLARIFICATION_NEEDED *before* schema retrieval, then direct_response invented
generic metrics (sales, performance, attendance) that may not exist in the DB.

After the fix:
- intent classifier is route-only (never emits CLARIFICATION_NEEDED)
- clarification happens only after schema-grounded interpretation + policy
"""

from src.agent.graph import route_after_context, route_after_interpretation, route_intent
from src.agent.prompts.intent import INTENT_SYSTEM_PROMPT


def test_intent_prompt_is_route_only():
    assert "CLARIFICATION_NEEDED" not in INTENT_SYSTEM_PROMPT
    assert "SQL_QUERY" in INTENT_SYSTEM_PROMPT
    assert "META" in INTENT_SYSTEM_PROMPT
    assert "CHIT_CHAT" in INTENT_SYSTEM_PROMPT


def test_classifier_clarification_routes_direct_but_sql_goes_to_context():
    """CLARIFICATION_NEEDED may still be set later by the policy gate."""
    assert route_intent({"intent": "SQL_QUERY"}) == "sql"
    assert route_intent({"intent": "CLARIFICATION_NEEDED"}) == "direct"
    assert route_intent({"intent": "META"}) == "direct"


def test_after_context_resolves_before_generate(monkeypatch):
    from src.config.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MERGE_INTERPRET_GENERATE", "false")
    get_settings.cache_clear()
    assert route_after_context({}) == "resolve"
    assert (
        route_after_context({"ambiguity": {"should_clarify": True}}) == "clarify"
    )
    get_settings.cache_clear()


def test_after_interpretation_can_clarify_or_generate():
    assert route_after_interpretation({}) == "generate"
    assert (
        route_after_interpretation({"ambiguity": {"should_clarify": True}})
        == "clarify"
    )
