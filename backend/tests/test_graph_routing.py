from src.agent.graph import (
    route_after_context,
    route_after_execute,
    route_after_validate,
    route_intent,
)


def test_route_after_context_clarifies():
    assert (
        route_after_context({"ambiguity": {"should_clarify": True}}) == "clarify"
    )


def test_route_after_context_generates_by_default():
    assert route_after_context({}) == "generate"
    assert route_after_context({"ambiguity": {"should_clarify": False}}) == "generate"


def test_route_intent_sql_vs_direct():
    assert route_intent({"intent": "SQL_QUERY"}) == "sql"
    assert route_intent({"intent": "CLARIFICATION_NEEDED"}) == "direct"


def test_route_after_validate_clarifies_before_execute():
    assert (
        route_after_validate(
            {"ambiguity": {"should_clarify": True}, "error": None}
        )
        == "clarify"
    )
    assert route_after_validate({"error": None}) == "execute"


def test_route_after_execute_clarifies_instead_of_explain_retry():
    assert (
        route_after_execute(
            {"ambiguity": {"should_clarify": True}, "error": None}
        )
        == "clarify"
    )
    assert route_after_execute({"error": None}) == "format"
