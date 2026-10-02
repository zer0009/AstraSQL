from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Literal

from langgraph.graph import END, START, StateGraph

from src.agent.nodes import (
    ambiguity_gate,
    context_retriever_node,
    direct_response,
    intent_classifier,
    interpretation_resolver,
    query_executor,
    query_generator,
    query_validator,
    response_formatter,
)
from src.agent.state import AgentState
from src.agent.utils import max_retries
from src.config.settings import get_settings
from src.observability.usage import usage_stage

_SQL_INTENTS = frozenset({"SQL_QUERY"})


def _with_stage(stage: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a node so LLM calls inside it are labelled with ``stage``."""

    @wraps(fn)
    async def _wrapped(state: AgentState, config: Any = None) -> Any:
        with usage_stage(stage):
            if config is None:
                return await fn(state)
            return await fn(state, config)

    return _wrapped


def route_intent(state: AgentState) -> Literal["sql", "direct"]:
    intent = (state.get("intent") or "SQL_QUERY").upper()
    if intent in _SQL_INTENTS:
        return "sql"
    return "direct"


def route_after_parallel_join(
    state: AgentState,
) -> Literal["resolve", "generate", "clarify", "direct"]:
    """Join after parallel intent + retrieval."""
    intent = (state.get("intent") or "SQL_QUERY").upper()
    if intent not in _SQL_INTENTS:
        return "direct"
    ambiguity = state.get("ambiguity") or {}
    if isinstance(ambiguity, dict) and ambiguity.get("should_clarify"):
        return "clarify"
    settings = get_settings()
    if bool(getattr(settings, "merge_interpret_generate", False)):
        return "generate"
    return "resolve"


def route_after_context(
    state: AgentState,
) -> Literal["resolve", "generate", "clarify"]:
    ambiguity = state.get("ambiguity") or {}
    if isinstance(ambiguity, dict) and ambiguity.get("should_clarify"):
        return "clarify"
    # Merged interpret+generate skips the separate resolver LLM call.
    settings = get_settings()
    if bool(getattr(settings, "merge_interpret_generate", False)):
        return "generate"
    return "resolve"


def route_after_interpretation(
    state: AgentState,
) -> Literal["generate", "clarify"]:
    ambiguity = state.get("ambiguity") or {}
    if isinstance(ambiguity, dict) and ambiguity.get("should_clarify"):
        return "clarify"
    return "generate"


def route_after_generate(
    state: AgentState,
) -> Literal["gate", "validate", "direct", "clarify"]:
    """Run execution-evidence gate when flagged; else go straight to validate."""
    ambiguity = state.get("ambiguity") or {}
    if isinstance(ambiguity, dict):
        status = str(ambiguity.get("status") or "").lower()
        if status == "not_a_data_question":
            return "direct"
        if ambiguity.get("should_clarify") or status == "unanswerable":
            return "clarify"
    settings = get_settings()
    if not bool(getattr(settings, "execution_evidence_gate", True)):
        return "validate"
    if not isinstance(ambiguity, dict):
        return "validate"
    if ambiguity.get("needs_execution_gate") or ambiguity.get("decision_points"):
        return "gate"
    return "validate"


def route_after_gate(
    state: AgentState,
) -> Literal["validate", "clarify"]:
    ambiguity = state.get("ambiguity") or {}
    if isinstance(ambiguity, dict) and ambiguity.get("should_clarify"):
        return "clarify"
    return "validate"


def route_after_validate(
    state: AgentState,
) -> Literal["execute", "retry", "fail", "clarify"]:
    ambiguity = state.get("ambiguity") or {}
    if isinstance(ambiguity, dict) and ambiguity.get("should_clarify"):
        return "clarify"
    if not state.get("error"):
        return "execute"
    if int(state.get("retries") or 0) < max_retries():
        return "retry"
    return "fail"


def route_after_execute(
    state: AgentState,
) -> Literal["format", "retry", "fail", "clarify"]:
    ambiguity = state.get("ambiguity") or {}
    if isinstance(ambiguity, dict) and ambiguity.get("should_clarify"):
        return "clarify"
    if state.get("shape_retry") and int(state.get("retries") or 0) < max_retries():
        return "retry"
    if not state.get("error"):
        return "format"
    if int(state.get("retries") or 0) < max_retries():
        return "retry"
    return "fail"


def _passthrough_join(state: AgentState) -> dict[str, Any]:
    """No-op join node so parallel intent + retrieval can converge."""
    return {}


def build_graph():
    """Compile the AstraSQL LangGraph pipeline."""
    g = StateGraph(AgentState)
    g.add_node("intent_classifier", _with_stage("intent_classifier", intent_classifier))
    g.add_node(
        "context_retriever",
        _with_stage("context_retriever", context_retriever_node),
    )
    g.add_node("parallel_join", _passthrough_join)
    g.add_node(
        "interpretation_resolver",
        _with_stage("interpretation_resolver", interpretation_resolver),
    )
    g.add_node("query_generator", _with_stage("query_generator", query_generator))
    g.add_node("ambiguity_gate", _with_stage("ambiguity_gate", ambiguity_gate))
    g.add_node("query_validator", _with_stage("query_validator", query_validator))
    g.add_node("query_executor", _with_stage("query_executor", query_executor))
    g.add_node(
        "response_formatter",
        _with_stage("response_formatter", response_formatter),
    )
    g.add_node("direct_response", _with_stage("direct_response", direct_response))

    # Parallel intent+retrieval fan-out is disabled: LangGraph LastValue keys
    # (error/steps) need Annotated reducers first. Prefer merge_interpret_generate
    # which skips both intent and the separate resolver (single schema-aware call).
    settings = get_settings()
    if bool(getattr(settings, "merge_interpret_generate", False)):
        # Merged path: retrieval -> generate (intent folded into generator).
        g.add_edge(START, "context_retriever")
    else:
        g.add_edge(START, "intent_classifier")
        g.add_conditional_edges(
            "intent_classifier",
            route_intent,
            {"sql": "context_retriever", "direct": "direct_response"},
        )
    g.add_conditional_edges(
        "context_retriever",
        route_after_context,
        {
            "resolve": "interpretation_resolver",
            "generate": "query_generator",
            "clarify": "direct_response",
        },
    )
    g.add_conditional_edges(
        "interpretation_resolver",
        route_after_interpretation,
        {"generate": "query_generator", "clarify": "direct_response"},
    )
    g.add_conditional_edges(
        "query_generator",
        route_after_generate,
        {
            "gate": "ambiguity_gate",
            "validate": "query_validator",
            "direct": "direct_response",
            "clarify": "direct_response",
        },
    )
    g.add_conditional_edges(
        "ambiguity_gate",
        route_after_gate,
        {"validate": "query_validator", "clarify": "direct_response"},
    )
    g.add_conditional_edges(
        "query_validator",
        route_after_validate,
        {
            "execute": "query_executor",
            "retry": "query_generator",
            "fail": "response_formatter",
            "clarify": "direct_response",
        },
    )
    g.add_conditional_edges(
        "query_executor",
        route_after_execute,
        {
            "format": "response_formatter",
            "retry": "query_generator",
            "fail": "response_formatter",
            "clarify": "direct_response",
        },
    )
    g.add_edge("response_formatter", END)
    g.add_edge("direct_response", END)
    return g.compile()


def get_graph():
    """Compile a fresh graph so node code is never a stale process-level cache."""
    return build_graph()
