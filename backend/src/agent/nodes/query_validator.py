from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.agent.nodes.validator_helpers import (
    _fail_or_retry,
    _pass_without_llm,
    check_catalog,
    check_readable_dimensions,
)
from src.agent.prompts.validator import render_validator_prompt
from src.agent.provenance import clarify_or_none, clarify_unbound
from src.agent.sql_guards import (
    rewrite_invalid_json_operators,
    validate_syntax,
)
from src.agent.sql_repair import repair_sqlite_sql
from src.agent.state import AgentState
from src.agent.utils import (
    append_step,
    classify_retry_type,
    extract_json,
    get_configurable,
    message_text,
)
from src.config.settings import get_settings
from src.providers.llm import get_llm_provider, stage_chat_kwargs

# Backward-compatible re-exports (helpers live in validator_helpers).
__all__ = ["check_catalog", "query_validator", "validate_syntax"]


def _should_escalate_to_llm(state: AgentState, settings: Any) -> bool:
    """LLM validator only when flags / retries suggest semantic risk."""
    if int(state.get("retries") or 0) > 0:
        return True
    retry = (state.get("retry_context") or "").upper()
    if any(
        token in retry
        for token in (
            "EMPTY_RESULT",
            "SUSPICIOUS",
            "SYNTAX_ERROR",
            "WRONG_COLUMN",
            "WRONG_TABLE",
            "TYPE_MISMATCH",
            "ENTITY_MAPPING",
        )
    ):
        return True
    amb = state.get("ambiguity") if isinstance(state.get("ambiguity"), dict) else {}
    if amb.get("needs_execution_gate") or amb.get("decision_points"):
        return True
    return False


async def query_validator(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Validate SQL: Layer 1 always; LLM only when mode=full or flags fire.

    Modes (settings.validator_mode):
      - full: Layer 1 + LLM semantic validator (legacy)
      - deterministic: Layer 1 + catalog/readability; LLM only on flags/retries
      - off: Layer 1 only; skip LLM when syntax/DML passes
    """
    cfg = get_configurable(config)
    db_provider = cfg.get("db_provider")
    settings = get_settings()
    mode = (settings.validator_mode or "deterministic").strip().lower()
    if mode not in {"full", "deterministic", "off"}:
        mode = "deterministic"

    sql = (state.get("corrected_sql") or state.get("sql") or "").strip()
    question = state.get("question") or ""
    context = state.get("context") or {}
    retries = int(state.get("retries") or 0)

    if db_provider is None:
        return {
            "error": "Missing db_provider in configurable",
            "steps": append_step(state, "validate_error", "db_provider missing"),
        }
    if not sql:
        return _fail_or_retry(
            state,
            sql="",
            message="No SQL to validate",
            retries=retries,
            is_dml=False,
        )

    dialect = db_provider.sqlglot_dialect()
    clarify = clarify_or_none(state, sql, dialect)
    if clarify is not None:
        return clarify

    # Layer 1 — static AST / DML guard
    ok, err, is_dml = validate_syntax(sql, dialect)
    if not ok:
        steps = append_step(
            state,
            "validate_syntax_failed",
            err or "Syntax validation failed",
            sql=sql,
            dml_blocked=is_dml,
        )
        state_with_steps = {**state, "steps": steps}
        bind_failed = "Unbound parameter" in (err or "")
        if bind_failed:
            return clarify_unbound(state_with_steps, sql, dialect)
        return _fail_or_retry(
            state_with_steps,
            sql=sql,
            message=err or "Syntax validation failed",
            retries=retries,
            is_dml=is_dml,
            retry_type="SYNTAX_ERROR",
        )

    # Deterministic repairs (opt-in; after successful Layer-1 syntax)
    needs_repair = False
    if db_provider is not None and hasattr(db_provider, "needs_deterministic_repair"):
        needs_repair = bool(db_provider.needs_deterministic_repair())
    elif (dialect or "").lower() == "sqlite":
        needs_repair = True
    if (
        bool(getattr(settings, "deterministic_sql_repair", True))
        and needs_repair
    ):
        repaired_sql, repair_tags = repair_sqlite_sql(sql)
        if repair_tags and repaired_sql and repaired_sql != sql:
            sql = repaired_sql
            state = {
                **state,
                "steps": append_step(
                    state,
                    "sql_repair",
                    f"Applied deterministic repairs: {', '.join(repair_tags)}",
                    sql=sql,
                    repair_tags=repair_tags,
                ),
            }

    if mode == "off":
        return _pass_without_llm(state, sql=sql, mode=mode)

    # Prefer labels over raw FK ids whenever the schema exposes them.
    readability_issues = check_readable_dimensions(
        sql,
        dialect,
        enriched_schema=str(context.get("enriched_schema") or ""),
    )
    if readability_issues and retries < int(settings.max_retries or 0):
        return _fail_or_retry(
            state,
            sql=sql,
            message="; ".join(readability_issues),
            retries=retries,
            is_dml=False,
            issues=readability_issues,
            retry_type="ENTITY_MAPPING",
        )

    if mode == "deterministic":
        catalog_issues = check_catalog(
            sql,
            dialect,
            selected_tables=list(context.get("selected_tables") or []),
            selected_columns=list(context.get("selected_columns") or []),
        )
        if catalog_issues:
            # Ambiguity-gate already executed this SQL successfully — trust
            # execution evidence over a heuristic catalog miss.
            prior = state.get("results") if isinstance(state.get("results"), dict) else None
            if state.get("cached_execution") and prior and "row_count" in prior:
                return _pass_without_llm(
                    state,
                    sql=sql,
                    mode=mode,
                    catalog_issues=catalog_issues,
                )
            return _fail_or_retry(
                state,
                sql=sql,
                message="; ".join(catalog_issues),
                retries=retries,
                is_dml=False,
                issues=catalog_issues,
                retry_type="WRONG_COLUMN"
                if any("column" in i.lower() for i in catalog_issues)
                else "WRONG_TABLE",
            )
        if not _should_escalate_to_llm(state, settings):
            return _pass_without_llm(
                state, sql=sql, mode=mode, catalog_issues=catalog_issues
            )
        # Fall through to LLM validator when flags / retries fire.

    # Layer 2 — LLM semantic validator (full mode or escalated deterministic)
    try:
        checklist_items = db_provider.dialect_validator_checklist() or []
        checklist_text = "\n".join(f"- {item}" for item in checklist_items)
        system = render_validator_prompt(
            dialect_name=db_provider.dialect_name(),
            enriched_schema_for_selected_tables=context.get("enriched_schema")
            or "",
            dialect_validator_checklist=checklist_text,
            generated_sql=sql,
            user_question=question,
        )
        llm = get_llm_provider().get_chat_model(
            **stage_chat_kwargs("query_validator", settings=settings)
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=system),
                HumanMessage(content="Validate the SQL and return JSON only."),
            ],
            config=config,
        )
        parsed = extract_json(message_text(response))
        issues = parsed.get("issues_found") or []
        if not isinstance(issues, list):
            issues = [str(issues)]
        corrected = str(parsed.get("corrected_sql") or sql).strip() or sql
        is_valid = bool(parsed.get("is_valid", True))
        error_type = str(parsed.get("error_type") or "").strip() or None
    except Exception as exc:
        return _fail_or_retry(
            state,
            sql=sql,
            message=f"Semantic validation failed: {exc}",
            retries=retries,
            is_dml=False,
            retry_type="OTHER",
        )

    # Prefer corrected SQL; apply deterministic type guards before execute.
    if corrected:
        guarded, guard_issues = rewrite_invalid_json_operators(
            corrected,
            dialect=db_provider.sqlglot_dialect(),
            enriched_schema=context.get("enriched_schema") or "",
        )
        if guard_issues:
            corrected = guarded
            issues = list(issues) + guard_issues
            is_valid = False
            error_type = error_type or "TYPE_MISMATCH"

        merged = {**state, "sql": corrected, "corrected_sql": corrected}
        clarify = clarify_or_none(merged, corrected, dialect)
        if clarify is not None:
            return clarify

        ok, err, is_dml = validate_syntax(corrected, dialect)
        if not ok:
            bind_failed = "Unbound parameter" in (err or "")
            if bind_failed:
                return clarify_unbound(merged, corrected, dialect)
            return _fail_or_retry(
                state,
                sql=corrected,
                message=err or "Syntax validation failed",
                retries=retries,
                is_dml=is_dml,
                retry_type="SYNTAX_ERROR",
            )

        detail = (
            "SQL validated"
            if is_valid and not issues
            else f"SQL corrected ({len(issues)} issue(s))"
        )
        return {
            "sql": corrected,
            "corrected_sql": corrected,
            "error": None,
            "steps": append_step(
                state,
                "sql_validated",
                detail,
                issues=issues,
                is_valid=is_valid,
                error_type=error_type,
                sql=corrected,
                json_ops_rewritten=bool(guard_issues),
                validator_mode=mode,
            ),
        }

    retry_type = classify_retry_type(
        error="Validator returned no corrected SQL",
        issues=issues,
        error_type=error_type,
    )
    return _fail_or_retry(
        state,
        sql=sql,
        message="Validator returned no corrected SQL",
        retries=retries,
        is_dml=False,
        issues=issues,
        retry_type=retry_type,
    )
