from __future__ import annotations

from typing import Any, Optional

import sqlglot
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from sqlglot import exp
from sqlglot.errors import ParseError

from src.agent.prompts.validator import render_validator_prompt
from src.agent.sql_guards import rewrite_invalid_json_operators
from src.agent.state import AgentState
from src.agent.utils import (
    append_step,
    build_retry_context,
    classify_retry_type,
    extract_json,
    get_configurable,
    max_retries,
    message_text,
)
from src.config.settings import get_settings
from src.providers.llm import get_llm_provider

_DML_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
)


def validate_syntax(
    sql: str, sqlglot_dialect: str
) -> tuple[bool, Optional[str], bool]:
    """Layer 1: parse + block DML.

    Returns (ok, error_message, is_dml_block).
    """
    try:
        tree = sqlglot.parse_one(sql, dialect=sqlglot_dialect)
    except ParseError as e:
        return False, f"SQL syntax error: {e}", False
    except Exception as e:
        return False, f"SQL parse failed: {e}", False

    if isinstance(tree, _DML_TYPES) or any(tree.find(t) for t in _DML_TYPES):
        kind = type(tree).__name__
        for t in _DML_TYPES:
            found = tree.find(t)
            if found is not None:
                kind = type(found).__name__
                break
        return (
            False,
            (
                f"DML statement blocked: {kind}. "
                "Only SELECT/WITH queries are permitted."
            ),
            True,
        )
    return True, None, False


async def query_validator(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Two-layer validation: sqlglot AST guard, then LLM semantic review."""
    cfg = get_configurable(config)
    db_provider = cfg.get("db_provider")
    settings = get_settings()
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

    # Layer 1 — static AST / DML guard
    ok, err, is_dml = validate_syntax(sql, db_provider.sqlglot_dialect())
    if not ok:
        steps = append_step(
            state,
            "validate_syntax_failed",
            err or "Syntax validation failed",
            sql=sql,
            dml_blocked=is_dml,
        )
        state_with_steps = {**state, "steps": steps}
        return _fail_or_retry(
            state_with_steps,
            sql=sql,
            message=err or "Syntax validation failed",
            retries=retries,
            is_dml=is_dml,
            retry_type="SYNTAX_ERROR",
        )

    # Layer 2 — LLM semantic validator
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


def _fail_or_retry(
    state: AgentState,
    *,
    sql: str,
    message: str,
    retries: int,
    is_dml: bool,
    issues: Optional[list] = None,
    retry_type: Optional[str] = None,
) -> dict[str, Any]:
    """Set error/retry_context; exhaust retries immediately for DML blocks."""
    limit = max_retries()
    typed = classify_retry_type(
        error=message,
        issues=issues,
        error_type=retry_type,
        is_syntax=(retry_type == "SYNTAX_ERROR"),
    )
    steps = list(state.get("steps") or [])
    if not steps or steps[-1].get("name") not in {
        "validate_syntax_failed",
        "validate_retry",
        "validate_failed",
    }:
        steps = append_step(
            state,
            "validate_failed" if is_dml or retries >= limit else "validate_retry",
            message,
            sql=sql,
            issues=issues or [],
            retry_type=typed,
        )

    if is_dml:
        return {
            "error": message,
            "retries": limit,
            "retry_context": "",
            "steps": steps,
        }

    retry_ctx = build_retry_context(
        previous_sql=sql,
        error=message,
        prior_context=state.get("retry_context") or "",
        retry_type=typed,
    )
    return {
        "error": message,
        "retry_context": retry_ctx,
        "steps": steps,
    }
