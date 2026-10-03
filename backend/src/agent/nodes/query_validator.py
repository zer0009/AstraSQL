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
from src.providers.llm import get_llm_provider

# Backward-compatible re-exports (helpers live in validator_helpers).
__all__ = ["check_catalog", "query_validator", "validate_syntax"]


async def query_validator(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Validate SQL: Layer 1 always; LLM only when validator_mode=full.

    Modes (settings.validator_mode):
      - full: Layer 1 + LLM semantic validator (legacy)
      - deterministic: Layer 1 + optional catalog checks; skip LLM
      - off: Layer 1 only; skip LLM when syntax/DML passes
    """
    cfg = get_configurable(config)
    db_provider = cfg.get("db_provider")
    settings = get_settings()
    mode = (settings.validator_mode or "full").strip().lower()
    if mode not in {"full", "deterministic", "off"}:
        mode = "full"

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
        return _pass_without_llm(
            state, sql=sql, mode=mode, catalog_issues=catalog_issues
        )

    # Layer 2 — LLM semantic validator (full mode)
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
            temperature=0.0,
            max_tokens=settings.llm_max_tokens,
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
