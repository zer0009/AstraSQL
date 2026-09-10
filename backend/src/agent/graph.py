from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from src.agent.nodes import (
    context_retriever_node,
    direct_response,
    intent_classifier,
    query_executor,
    query_generator,
    query_validator,
    response_formatter,
)
from src.agent.state import AgentState
from src.agent.utils import max_retries

_SQL_INTENTS = frozenset({"SQL_QUERY"})


def route_intent(state: AgentState) -> Literal["sql", "direct"]:
    intent = (state.get("intent") or "SQL_QUERY").upper()
    if intent in _SQL_INTENTS:
        return "sql"
    return "direct"


def route_after_validate(
    state: AgentState,
) -> Literal["execute", "retry", "fail"]:
    if not state.get("error"):
        return "execute"
    if int(state.get("retries") or 0) < max_retries():
        return "retry"
    return "fail"


def route_after_execute(
    state: AgentState,
) -> Literal["format", "retry", "fail"]:
    if not state.get("error"):
        return "format"
    if int(state.get("retries") or 0) < max_retries():
        return "retry"
    return "fail"


def build_graph():
    """Compile the AstraSQL LangGraph pipeline."""
    g = StateGraph(AgentState)
    g.add_node("intent_classifier", intent_classifier)
    g.add_node("context_retriever", context_retriever_node)
    g.add_node("query_generator", query_generator)
    g.add_node("query_validator", query_validator)
    g.add_node("query_executor", query_executor)
    g.add_node("response_formatter", response_formatter)
    g.add_node("direct_response", direct_response)

    g.add_edge(START, "intent_classifier")
    g.add_conditional_edges(
        "intent_classifier",
        route_intent,
        {"sql": "context_retriever", "direct": "direct_response"},
    )
    g.add_edge("context_retriever", "query_generator")
    g.add_edge("query_generator", "query_validator")
    g.add_conditional_edges(
        "query_validator",
        route_after_validate,
        {
            "execute": "query_executor",
            "retry": "query_generator",
            "fail": "response_formatter",
        },
    )
    g.add_conditional_edges(
        "query_executor",
        route_after_execute,
        {
            "format": "response_formatter",
            "retry": "query_generator",
            "fail": "response_formatter",
        },
    )
    g.add_edge("response_formatter", END)
    g.add_edge("direct_response", END)
    return g.compile()


# Module-level compiled graph (nodes read session/connection from config).
_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH
