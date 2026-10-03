from __future__ import annotations

from fastapi import APIRouter

from src.api.schemas import AgentGraphOut, PublicSettingsOut
from src.config.settings import get_settings
from src.providers.database import list_database_types

router = APIRouter(tags=["settings"])


@router.get("/public", response_model=PublicSettingsOut)
async def public_settings() -> PublicSettingsOut:
    settings = get_settings()
    return PublicSettingsOut(
        app_name=settings.app_name,
        llm_provider=settings.llm_provider,
        model=settings.llm_model,
        max_rows=settings.max_result_rows,
        database_types=list_database_types(),
        execution_evidence_gate=bool(settings.execution_evidence_gate),
        merge_interpret_generate=bool(settings.merge_interpret_generate),
        ambiguity_policy=str(settings.ambiguity_policy or "balanced"),
        relationship_discovery_enabled=bool(settings.relationship_discovery_enabled),
        relationship_auto_approve=bool(settings.relationship_auto_approve),
        learning_loop_enabled=bool(settings.learning_loop_enabled),
        sse_row_preview_limit=100,
    )


@router.get("/agent-graph", response_model=AgentGraphOut)
async def agent_graph() -> AgentGraphOut:
    """Return the compiled LangGraph structure as Mermaid for the UI."""
    from src.agent.graph import get_graph

    settings = get_settings()
    graph = get_graph()
    drawable = graph.get_graph()
    try:
        mermaid = drawable.draw_mermaid()
    except (AttributeError, NotImplementedError, TypeError, ValueError):
        # Fallback when draw_mermaid is unavailable.
        nodes = sorted({str(n) for n in (drawable.nodes or {})})
        edges = []
        for edge in drawable.edges or []:
            source = getattr(edge, "source", None)
            target = getattr(edge, "target", None)
            if source is None or target is None:
                continue
            edges.append(f"  {source} --> {target}")
        mermaid = "flowchart TD\n" + "\n".join(f"  {n}" for n in nodes)
        if edges:
            mermaid += "\n" + "\n".join(edges)
    nodes = sorted({str(n) for n in (getattr(drawable, "nodes", None) or {})})
    return AgentGraphOut(
        mermaid=mermaid,
        nodes=nodes,
        merge_interpret_generate=bool(settings.merge_interpret_generate),
        execution_evidence_gate=bool(settings.execution_evidence_gate),
    )
