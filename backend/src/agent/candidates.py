"""Adaptive multi-candidate SQL generation.

Generates candidates in parallel (merged prompt by default), executes each
once, and picks consensus via ``results_equal_values``. Accepts a seed SQL
(from the primary generator) so the ambiguity gate never regenerates it.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.agent.prompts.generator import (
    format_conversation_history,
    render_generator_prompt,
    render_merged_generator_prompt,
)
from src.agent.result_compare import results_equal_values
from src.agent.utils import extract_json, message_text
from src.config.settings import get_settings
from src.providers.llm import get_llm_provider, stage_chat_kwargs

# Prompt style variants — keep cheap: reuse one system template + suffix.
_VARIANT_SUFFIXES: dict[str, str] = {
    "direct": (
        "\n\nVARIANT: direct — Prefer a concise reading. "
        "Return JSON with status/interpretation and a correct \"sql\".\n"
    ),
    "plan_first": (
        "\n\nVARIANT: plan-first — Prefer explicit JOINs and schema-faithful "
        "column names. Return JSON with status/interpretation and \"sql\".\n"
    ),
    "alt_reading": (
        "\n\nVARIANT: alternative — If the question admits another schema-grounded "
        "reading, produce that alternative SQL. Still return valid JSON.\n"
    ),
}


def _variant_names(count: int) -> list[str]:
    names = ["plan_first", "direct", "alt_reading"]
    while len(names) < count:
        names.append(names[len(names) % 3])
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


def _build_system(
    *,
    state: dict[str, Any],
    db_provider: Any,
    settings: Any,
    question: str,
    retry_context: str,
    use_merged: bool,
) -> str:
    context = state.get("context") or {}
    history_text = format_conversation_history(
        state.get("conversation_history") or []
    )
    assumption = str(state.get("assumption") or "").strip()
    if not assumption:
        amb = state.get("ambiguity") or {}
        if isinstance(amb, dict):
            assumption = str(amb.get("assumption") or "").strip()

    if use_merged:
        return render_merged_generator_prompt(
            dialect_name=db_provider.dialect_name(),
            enriched_schema=context.get("enriched_schema") or "",
            business_rules=context.get("business_rules") or "",
            golden_records=context.get("golden_records_text") or "",
            conversation_history=history_text,
            dialect_prompt_rules=db_provider.dialect_prompt_rules(),
            max_rows=settings.max_result_rows,
            retry_context=retry_context,
            user_question=question,
            current_date=date.today().isoformat(),
            schema_digest="",  # digest is redundant with enriched_schema
        )
    return render_generator_prompt(
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


async def _generate_one(
    *,
    system: str,
    question: str,
    variant: str,
    settings: Any,
    config: RunnableConfig | None,
    escalate: bool = False,
) -> str:
    suffix = _VARIANT_SUFFIXES.get(variant, "")
    llm = get_llm_provider().get_chat_model(
        **stage_chat_kwargs(
            "candidates",
            settings=settings,
            escalate=escalate,
        )
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
    seed_sql: str | None = None,
    execute: bool = True,
    use_merged: bool | None = None,
) -> tuple[str, dict[str, Any]]:
    """Generate up to N SQL candidates in parallel, execute once, pick consensus.

    ``seed_sql`` (from the primary generator) is always candidate 0 and is never
    regenerated. Returns ``(selected_sql, meta)`` where meta includes candidate
    SQLs, executed results, and which consensus path was used.
    """
    count = max(1, min(int(candidate_count), 5))
    settings = settings or get_settings()
    if use_merged is None:
        use_merged = bool(
            getattr(settings, "always_merged_schema", True)
            or getattr(settings, "merge_interpret_generate", True)
        )

    seed = (seed_sql or str(state.get("sql") or "")).strip()
    sqls: list[str] = []
    if seed:
        sqls.append(seed)

    need = max(0, count - len(sqls))
    variants = _variant_names(need) if need else []
    base_system = _build_system(
        state=state,
        db_provider=db_provider,
        settings=settings,
        question=question,
        retry_context=retry_context,
        use_merged=use_merged,
    )

    if need:
        tasks = [
            _generate_one(
                system=base_system,
                question=question,
                variant=variant,
                settings=settings,
                config=config,
                escalate=bool(retry_context.strip()),
            )
            for variant in variants
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for item in results:
            if isinstance(item, Exception):
                continue
            sql = str(item or "").strip()
            if sql and sql not in sqls:
                sqls.append(sql)

    if not sqls:
        raise ValueError("Multi-candidate generation produced no SQL")

    executed: list[dict[str, Any]] = []
    if execute and len(sqls) > 1:
        async def _exec(sql: str) -> dict[str, Any]:
            try:
                results = await db_provider.execute_readonly(
                    sql, max_rows=settings.max_result_rows
                )
                return {"sql": sql, "results": results}
            except Exception:
                return {"sql": sql, "results": None}

        executed = list(await asyncio.gather(*[_exec(s) for s in sqls]))
        chosen = pick_consensus_sql(executed)
        if chosen is None:
            return sqls[0], {
                "candidates": sqls,
                "selected_by": "first_all_failed",
                "variants": variants,
                "executed": executed,
                "executed_ok": 0,
            }
        ok_count = sum(1 for e in executed if isinstance(e.get("results"), dict))
        return chosen, {
            "candidates": sqls,
            "selected_by": "consensus" if ok_count > 1 else "sole_success",
            "variants": variants,
            "executed": executed,
            "executed_ok": ok_count,
            "selected_sql": chosen,
        }

    # Single candidate or execute=False: return without consensus execute.
    if execute and sqls:
        try:
            results = await db_provider.execute_readonly(
                sqls[0], max_rows=settings.max_result_rows
            )
            executed = [{"sql": sqls[0], "results": results}]
        except Exception:
            executed = [{"sql": sqls[0], "results": None}]

    return sqls[0], {
        "candidates": sqls,
        "selected_by": "single" if len(sqls) == 1 else "seed_only",
        "variants": variants[: len(sqls)],
        "executed": executed,
        "executed_ok": sum(
            1 for e in executed if isinstance(e.get("results"), dict)
        ),
    }
