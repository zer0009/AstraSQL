"""Execution-evidence ambiguity gate node.

Runs after SQL generation when the resolver deferred an ask, or when the
merged generator flagged decision_points. Reuses the primary SQL as candidate
0, samples additional SQLs in parallel, executes each once, clusters by
denotation, and asks only on split clusters (unless answer_first is on).
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


def _results_for_sql(
    executed: list[dict[str, Any]], sql: str
) -> dict[str, Any] | None:
    for item in executed:
        if item.get("sql") == sql and isinstance(item.get("results"), dict):
            return item["results"]
    return None


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
    # Refine / resume turns must never re-ask.
    if state.get("allow_clarify") is False:
        return {
            "steps": append_step(
                state, "ambiguity_gate_skipped", "allow_clarify=false"
            ),
        }

    needs_gate = bool(ambiguity.get("needs_execution_gate"))
    decision_points = list(ambiguity.get("decision_points") or [])
    if not needs_gate and not decision_points:
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

    if ambiguity.get("should_clarify"):
        return {
            "steps": append_step(
                state, "ambiguity_gate_skipped", "already_clarifying"
            ),
        }

    question = state.get("question") or ""
    seed_sql = (state.get("corrected_sql") or state.get("sql") or "").strip()
    configured = int(getattr(settings, "ambiguity_sample_count", 3) or 3)
    configured = max(1, min(configured, 5))
    initial_k = min(2, configured) if configured >= 2 else configured

    dialect = ""
    try:
        if hasattr(db_provider, "sqlglot_dialect"):
            dialect = str(db_provider.sqlglot_dialect() or "")
        elif hasattr(db_provider, "dialect_name"):
            dialect = str(db_provider.dialect_name() or "")
    except Exception:
        dialect = ""

    async def _sample(count: int) -> tuple[list[str], list[dict[str, Any]]]:
        _sql, meta = await generate_and_select_candidates(
            state=state,
            config=config,
            db_provider=db_provider,
            settings=settings,
            candidate_count=count,
            question=question,
            retry_context=state.get("retry_context") or "",
            seed_sql=seed_sql or None,
            execute=True,
            use_merged=True,
        )
        sqls = list(meta.get("candidates") or [])
        executed = list(meta.get("executed") or [])
        if not sqls and seed_sql:
            sqls = [seed_sql]
        return sqls, executed

    try:
        candidate_sqls, executed = await _sample(initial_k)
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

    # If generate_and_select_candidates already executed, reuse those results.
    if not executed:
        executed = []
        for sql in candidate_sqls:
            try:
                results = await db_provider.execute_readonly(
                    sql, max_rows=settings.max_result_rows
                )
                executed.append({"sql": sql, "results": results})
            except Exception:
                executed.append({"sql": sql, "results": None})

    clusters = cluster_by_results(executed)
    if (
        configured > initial_k
        and len(clusters) > 1
        and len(candidate_sqls) < configured
    ):
        try:
            extra_sqls, extra_exec = await _sample(configured)
            seen = {c.get("sql") for c in executed}
            for item in extra_exec or []:
                sql = item.get("sql")
                if sql in seen:
                    continue
                executed.append(item)
                seen.add(sql)
            for sql in extra_sqls:
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

    # Answer-first: never block on clarify unless policy is strict.
    answer_first = bool(getattr(settings, "answer_first", True))
    policy = _connection_policy(connection, settings)
    force_ask = decision.should_clarify and (
        policy == "strict" or not answer_first
    )

    update: dict[str, Any] = {
        "ambiguity": {
            **ambiguity,
            "should_clarify": force_ask,
            "reason": decision.reason,
            "options": decision.options,
            "status": (
                decision.status
                if force_ask or not decision.should_clarify
                else "assumed"
            ),
            "decision_why": decision.decision_why
            + (";answer_first" if decision.should_clarify and not force_ask else ""),
            "assumption": decision.assumption
            or (
                "Assumed dominant reading; alternatives available"
                if decision.should_clarify and not force_ask
                else ""
            ),
            "clusters": decision.clusters,
            "readings": list(decision.readings or []),
            "gate": decision.gate,
            "needs_execution_gate": False,
            "alternatives": [
                o
                for o in (decision.options or [])
                if o and not str(o).lower().startswith("other")
            ],
        },
        "steps": append_step(
            state,
            "ambiguity_gate",
            (
                f"status={decision.status} clarify={force_ask} "
                f"why={decision.decision_why}"
            ),
            status=decision.status,
            should_clarify=force_ask,
            decision_why=decision.decision_why,
            cluster_count=len(decision.clusters),
            sample_count=len(candidate_sqls),
        ),
    }

    assumption = (
        decision.assumption
        or update["ambiguity"].get("assumption")
        or ""
    )
    if assumption:
        update["assumption"] = assumption

    selected = decision.selected_sql or seed_sql
    if selected and not force_ask:
        update["sql"] = selected
        update["corrected_sql"] = selected
        cached = _results_for_sql(executed, selected)
        if cached is not None:
            update["results"] = cached
            update["cached_execution"] = True

    if force_ask:
        update["intent"] = "CLARIFICATION_NEEDED"
        update["intent_reason"] = decision.reason
        if decision.options:
            update["clarification_options"] = decision.options
    elif decision.options:
        # Surface as follow-ups / alternatives chips (non-blocking).
        alts = [
            o
            for o in decision.options
            if o and not str(o).lower().startswith("other")
        ]
        update["follow_ups"] = alts
        update["clarification_options"] = alts

    return update
