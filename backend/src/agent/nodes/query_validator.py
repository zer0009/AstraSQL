from __future__ import annotations

from typing import Any, Optional

import sqlglot
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from sqlglot import exp
from sqlglot.errors import ParseError

from src.agent.prompts.validator import render_validator_prompt
from src.agent.provenance import clarify_or_none, clarify_unbound
from src.agent.sql_guards import find_bind_placeholders, rewrite_invalid_json_operators
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

    placeholders = find_bind_placeholders(sql)
    if placeholders:
        shown = ", ".join(placeholders[:5])
        return (
            False,
            (
                f"Unbound parameter {shown}: never emit $1 / :name placeholders. "
                "Write a literal only when the question names the value. "
                "If the person or id is unknown, do not guess."
            ),
            False,
        )

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


def _norm(name: str) -> str:
    return (name or "").strip().strip('"').strip("`").strip("[]").lower()


def check_catalog(
    sql: str,
    sqlglot_dialect: str,
    *,
    selected_tables: list[str] | None,
    selected_columns: list[dict] | None,
) -> list[str]:
    """Optional deterministic catalog check against context selections.

    Skips silently when selected_tables / selected_columns are unavailable.
    """
    tables = {_norm(t) for t in (selected_tables or []) if _norm(t)}
    col_pairs: set[tuple[str, str]] = set()
    bare_cols: set[str] = set()
    for item in selected_columns or []:
        if not isinstance(item, dict):
            continue
        t = _norm(str(item.get("table") or ""))
        c = _norm(str(item.get("column") or item.get("name") or ""))
        if c:
            bare_cols.add(c)
        if t and c:
            col_pairs.add((t, c))
            tables.add(t)

    if not tables and not bare_cols:
        return []

    try:
        tree = sqlglot.parse_one(sql, dialect=sqlglot_dialect)
    except Exception:
        return []

    issues: list[str] = []
    # Alias → physical table for qualified column checks.
    alias_map: dict[str, str] = {}
    for src in tree.find_all(exp.Table):
        name = _norm(src.name)
        if not name:
            continue
        alias = _norm(src.alias_or_name)
        if alias:
            alias_map[alias] = name
        alias_map[name] = name
        if tables and name not in tables:
            issues.append(f"Unknown table not in selected context: {src.name}")

    if bare_cols or col_pairs:
        for col in tree.find_all(exp.Column):
            cname = _norm(col.name)
            if not cname or cname == "*":
                continue
            table_ref = _norm(col.table) if col.table else ""
            if table_ref:
                physical = alias_map.get(table_ref, table_ref)
                if col_pairs and (physical, cname) not in col_pairs:
                    # Allow if bare name is selected (linker sometimes omits table).
                    if cname not in bare_cols:
                        issues.append(
                            f"Unknown column not in selected context: "
                            f"{table_ref}.{col.name}"
                        )
            elif bare_cols and cname not in bare_cols:
                # Unqualified — only flag when we have a bare-column allow-list.
                issues.append(
                    f"Unknown column not in selected context: {col.name}"
                )

    return issues


def _pass_without_llm(
    state: AgentState,
    *,
    sql: str,
    mode: str,
    catalog_issues: list[str] | None = None,
) -> dict[str, Any]:
    detail = f"SQL validated ({mode}; LLM skipped)"
    if catalog_issues:
        detail = f"SQL validated ({mode}; catalog OK)"
    return {
        "sql": sql,
        "corrected_sql": sql,
        "error": None,
        "steps": append_step(
            state,
            "sql_validated",
            detail,
            issues=catalog_issues or [],
            is_valid=True,
            error_type=None,
            sql=sql,
            validator_mode=mode,
        ),
    }


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

    if mode == "off":
        return _pass_without_llm(state, sql=sql, mode=mode)

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
