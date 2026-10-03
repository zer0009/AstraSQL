"""Adaptive multi-candidate SQL generation (minimal viable).

When ``sql_candidate_count > 1`` (or EMPTY_RESULT/SYNTAX retry boosts count),
generate slight prompt variants, execute each read-only, and pick consensus
via ``results_equal_values``. Default count=1 leaves the single-path unchanged.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.agent.prompts.generator import (
    format_conversation_history,
    render_generator_prompt,
)
from src.agent.result_compare import results_equal_values
from src.agent.utils import extract_json, message_text
from src.providers.llm import get_llm_provider

# Prompt style variants — keep cheap: reuse one system template + suffix.
_VARIANT_SUFFIXES: dict[str, str] = {
    "direct": (
        "\n\nVARIANT: direct — Skip the step-by-step scaffolding. "
        "Return JSON with an empty string for unused step fields and a correct "
        "\"sql\" that answers the question.\n"
    ),
    "plan_first": (
        "\n\nVARIANT: plan-first — Complete every step carefully before emitting "
        "\"sql\". Prefer explicit JOINs and schema-faithful column names.\n"
    ),
}


def _variant_names(count: int) -> list[str]:
    names = ["plan_first", "direct"]
    # Extra slots cycle the two styles (LLM still may diverge via suffix).
    while len(names) < count:
        names.append(names[len(names) % 2])
    return names[:count]


def pick_consensus_sql(
    candidates: list[dict[str, Any]],
) -> str | None:
    """Pure consensus picker over executed candidate result dicts.

    Each item: ``{"sql": str, "results": dict | None}`` where ``results`` is
    None (or missing) when execution failed.

    Returns the chosen SQL, or None when every candidate failed (caller keeps
    the first generated SQL for the normal validator path).
    """
    ok: list[tuple[str, dict]] = []
    for item in candidates:
        sql = str(item.get("sql") or "").strip()
        results = item.get("results")
        if not sql or not isinstance(results, dict):
            continue
        ok.append((sql, results))

    if not ok:
        return None
    if len(ok) == 1:
        return ok[0][0]

    # Group by denotation equality; prefer largest cluster, then earliest SQL.
    clusters: list[list[int]] = []
    for i, (_, res_i) in enumerate(ok):
        placed = False
        for cluster in clusters:
            rep = ok[cluster[0]][1]
            if results_equal_values(res_i, rep):
                cluster.append(i)
                placed = True
                break
        if not placed:
            clusters.append([i])

    best = max(clusters, key=lambda c: (len(c), -min(c)))
    return ok[best[0]][0]


async def _generate_one(
    *,
    system: str,
    question: str,
    variant: str,
    settings: Any,
    config: RunnableConfig | None,
) -> str:
    suffix = _VARIANT_SUFFIXES.get(variant, "")
    llm = get_llm_provider().get_chat_model(
        temperature=0.0,
        max_tokens=settings.llm_max_tokens,
    )
    response = await llm.ainvoke(
        [
            SystemMessage(content=system + suffix),
            HumanMessage(content=question or "Generate the SQL query."),
        ],
        config=config,
    )
    parsed = extract_json(message_text(response))
    sql = str(parsed.get("sql") or "").strip()
    if not sql:
        raise ValueError(f"Generator ({variant}) returned empty SQL")
    return sql


async def generate_and_select_candidates(
    *,
    state: dict[str, Any],
    config: RunnableConfig | None,
    db_provider: Any,
    settings: Any,
    candidate_count: int,
    question: str,
    retry_context: str = "",
) -> tuple[str, dict[str, Any]]:
    """Generate up to N SQL candidates, execute, pick consensus.

    Returns ``(selected_sql, meta)`` where meta includes candidate SQLs and
    which consensus path was used. If all executes fail, returns the first
    non-empty SQL (or raises if none were generated).
    """
    count = max(1, min(int(candidate_count), 5))
    context = state.get("context") or {}
    history_text = format_conversation_history(
        state.get("conversation_history") or []
    )
    assumption = str(state.get("assumption") or "").strip()
    if not assumption:
        amb = state.get("ambiguity") or {}
        if isinstance(amb, dict):
            assumption = str(amb.get("assumption") or "").strip()

    base_system = render_generator_prompt(
        dialect_name=db_provider.dialect_name(),
        enriched_schema=context.get("enriched_schema") or "",
        business_rules=context.get("business_rules") or "",
        golden_records=context.get("golden_records_text") or "",
        conversation_history=history_text,
        interpretation_assumption=assumption,
        dialect_prompt_rules=db_provider.dialect_prompt_rules(),
        max_rows=settings.max_result_rows,
        retry_context=retry_context,
        user_question=question,
        current_date=date.today().isoformat(),
    )

    variants = _variant_names(count)
    sqls: list[str] = []
    for variant in variants:
        try:
            sql = await _generate_one(
                system=base_system,
                question=question,
                variant=variant,
                settings=settings,
                config=config,
            )
            if sql and sql not in sqls:
                sqls.append(sql)
        except Exception:
            continue

    if not sqls:
        raise ValueError("Multi-candidate generation produced no SQL")

    if count == 1 or len(sqls) == 1:
        return sqls[0], {
            "candidates": sqls,
            "selected_by": "single",
            "variants": variants[: len(sqls)],
        }

    executed: list[dict[str, Any]] = []
    for sql in sqls:
        try:
            results = await db_provider.execute_readonly(
                sql, max_rows=settings.max_result_rows
            )
            executed.append({"sql": sql, "results": results})
        except Exception:
            executed.append({"sql": sql, "results": None})

    chosen = pick_consensus_sql(executed)
    if chosen is None:
        # All failed — keep first SQL for normal validator / retry path.
        return sqls[0], {
            "candidates": sqls,
            "selected_by": "first_all_failed",
            "variants": variants[: len(sqls)],
            "executed_ok": 0,
        }

    ok_count = sum(1 for e in executed if isinstance(e.get("results"), dict))
    return chosen, {
        "candidates": sqls,
        "selected_by": "consensus" if ok_count > 1 else "sole_success",
        "variants": variants[: len(sqls)],
        "executed_ok": ok_count,
        "selected_sql": chosen,
    }
