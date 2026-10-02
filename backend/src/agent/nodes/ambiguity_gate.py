"""Execution-evidence ambiguity gate node.

Runs after SQL generation when the resolver deferred an ask, or when the
merged generator flagged decision_points. Samples K candidate SQLs, executes
them, clusters by denotation, and asks only on split clusters.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from src.agent.candidates import generate_and_select_candidates
from src.agent.execution_gate import (
    cluster_by_results,
    decide_from_clusters,
    effective_dominance_threshold,
)
from src.agent.state import AgentState
from src.agent.utils import append_step, get_configurable
from src.config.settings import get_settings

logger = logging.getLogger(__name__)


def _connection_dominance(connection: Any) -> float | None:
    if connection is None:
        return None
    raw = getattr(connection, "ambiguity_dominance_threshold", None)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _connection_policy(connection: Any, settings: Any) -> str:
    if connection is not None:
        pol = getattr(connection, "ambiguity_policy", None)
        if pol:
            return str(pol).strip().lower()
    return str(getattr(settings, "ambiguity_policy", "balanced") or "balanced")


async def ambiguity_gate(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Sample/execute/cluster when needed; otherwise pass through."""
    settings = get_settings()
    cfg = get_configurable(config)
    db_provider = cfg.get("db_provider")
    connection = cfg.get("connection")

    if not bool(getattr(settings, "execution_evidence_gate", True)):
        return {
            "steps": append_step(
                state, "ambiguity_gate_skipped", "execution_evidence_gate=false"
            ),
        }

    ambiguity = state.get("ambiguity") if isinstance(state.get("ambiguity"), dict) else {}
    needs_gate = bool(ambiguity.get("needs_execution_gate"))
    decision_points = list(ambiguity.get("decision_points") or [])
    # Also run when merge path flagged intent-level points.
    if not needs_gate and not decision_points:
        # Cheap path: single SQL already generated and no flags — pass through.
        return {
            "steps": append_step(
                state, "ambiguity_gate_skipped", "no_flags", status="clear"
            ),
        }

    if db_provider is None:
        return {
            "steps": append_step(
                state, "ambiguity_gate_skipped", "db_provider missing"
            ),
        }

    # If we already clarified upstream, do not re-gate.
    if ambiguity.get("should_clarify"):
        return {
            "steps": append_step(
                state, "ambiguity_gate_skipped", "already_clarifying"
            ),
        }

    question = state.get("question") or ""
    # Adaptive K: sample 2 first; escalate to configured max only if they disagree.
    configured = int(getattr(settings, "ambiguity_sample_count", 3) or 3)
    configured = max(1, min(configured, 5))
    initial_k = min(2, configured) if configured >= 2 else configured

    dialect = ""
    try:
        dialect = db_provider.dialect_name()
    except Exception:
        dialect = ""

    async def _sample(count: int) -> list[str]:
        _sql, meta = await generate_and_select_candidates(
            state=state,
            config=config,
            db_provider=db_provider,
            settings=settings,
            candidate_count=count,
            question=question,
            retry_context=state.get("retry_context") or "",
        )
        sqls = list(meta.get("candidates") or [])
        if not sqls and state.get("sql"):
            sqls = [str(state.get("sql"))]
        return sqls

    # Reuse multi-candidate generation (variants) then cluster ourselves so we
    # keep all cluster metadata for ask/assume decisions.
    try:
        candidate_sqls = await _sample(initial_k)
    except Exception as exc:
        logger.warning("ambiguity_gate sample failed open: %s", exc)
        return {
            "ambiguity": {
                **ambiguity,
                "should_clarify": False,
                "status": "failed_open",
                "decision_why": "execution_gate;sample_exception",
                "reason": f"Gate failed open: {exc}",
                "gate": "execution_evidence",
            },
            "steps": append_step(
                state, "ambiguity_gate_failed_open", str(exc)
            ),
        }

    executed: list[dict[str, Any]] = []
    for sql in candidate_sqls:
        try:
            results = await db_provider.execute_readonly(
                sql, max_rows=settings.max_result_rows
            )
            executed.append({"sql": sql, "results": results})
        except Exception:
            executed.append({"sql": sql, "results": None})

    clusters = cluster_by_results(executed)
    # Escalate only when the first two disagree and a higher K is configured.
    if (
        configured > initial_k
        and len(clusters) > 1
        and len(candidate_sqls) < configured
    ):
        try:
            extra = await _sample(configured)
            seen = {c.get("sql") for c in executed}
            for sql in extra:
                if sql in seen:
                    continue
                try:
                    results = await db_provider.execute_readonly(
                        sql, max_rows=settings.max_result_rows
                    )
                    executed.append({"sql": sql, "results": results})
                except Exception:
                    executed.append({"sql": sql, "results": None})
                seen.add(sql)
            candidate_sqls = [str(c.get("sql") or "") for c in executed]
            clusters = cluster_by_results(executed)
        except Exception as exc:
            logger.warning("ambiguity_gate escalate sample failed open: %s", exc)
    threshold = effective_dominance_threshold(
        base=float(getattr(settings, "ambiguity_dominance_threshold", 0.67)),
        policy=_connection_policy(connection, settings),
        connection_override=_connection_dominance(connection),
    )
    decision = decide_from_clusters(
        clusters,
        dominance_threshold=threshold,
        dialect=dialect or None,
        intent_flagged=bool(decision_points),
        assumption_hint=str(
            state.get("assumption") or ambiguity.get("assumption") or ""
        ),
    )

    update: dict[str, Any] = {
        "ambiguity": {
            **ambiguity,
            "should_clarify": decision.should_clarify,
            "reason": decision.reason,
            "options": decision.options,
            "status": decision.status,
            "decision_why": decision.decision_why,
            "assumption": decision.assumption,
            "clusters": decision.clusters,
            "gate": decision.gate,
            "needs_execution_gate": False,
        },
        "steps": append_step(
            state,
            "ambiguity_gate",
            (
                f"status={decision.status} clarify={decision.should_clarify} "
                f"why={decision.decision_why}"
            ),
            status=decision.status,
            should_clarify=decision.should_clarify,
            decision_why=decision.decision_why,
            cluster_count=len(decision.clusters),
            sample_count=len(candidate_sqls),
        ),
    }

    if decision.assumption:
        update["assumption"] = decision.assumption

    if decision.selected_sql:
        update["sql"] = decision.selected_sql
        update["corrected_sql"] = decision.selected_sql
        # Cache executed result for the chosen SQL to avoid re-exec later.
        for item in executed:
            if item.get("sql") == decision.selected_sql and isinstance(
                item.get("results"), dict
            ):
                update["results"] = item["results"]
                break

    if decision.should_clarify:
        update["intent"] = "CLARIFICATION_NEEDED"
        update["intent_reason"] = decision.reason
        if decision.options:
            update["clarification_options"] = decision.options
    elif decision.options:
        update["follow_ups"] = decision.options

    return update
