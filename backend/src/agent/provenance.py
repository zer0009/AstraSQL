"""Catalog-key filter provenance. No business names, no language lists."""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from src.agent.catalog import deserialize_keys
from src.agent.sql_guards import find_bind_placeholders


@dataclass(frozen=True)
class MissingSlot:
    table: str
    column: str
    used_value: str


def _norm(name: str) -> str:
    return (name or "").strip().strip('"').lower()


def grounded_text(*texts: str) -> str:
    return "\n".join(t for t in texts if t).lower()


def literal_is_grounded(value: str, haystack: str) -> bool:
    text = (value or "").strip().strip("'\"")
    if not text:
        return False
    return text.lower() in (haystack or "")


def _param_label(node: exp.Expression) -> str | None:
    if isinstance(node, exp.Placeholder):
        name = node.this
        if name is None:
            return "?"
        token = str(name)
        return f"${token}" if token.isdigit() else f":{token}"
    if isinstance(node, exp.Parameter):
        name = node.this
        if name is None:
            return "?"
        token = str(name)
        return f"${token}" if token.isdigit() else f":{token}"
    return None


def _render_expr(node: exp.Expression, dialect: str) -> str:
    try:
        return node.sql(dialect=dialect)
    except Exception:
        return str(node)


def _eq_filters(sql: str, dialect: str) -> list[tuple[str, str, str, str]]:
    """Return (table, column, kind, value). Joins (column = column) are skipped.

    kind is bind | literal | expr.
    """
    try:
        tree = sqlglot.parse_one(sql, dialect=dialect)
    except Exception:
        return []

    alias_to_table: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        name = _norm(table.name or "")
        if not name:
            continue
        alias_to_table[name] = name
        alias = _norm(table.alias_or_name or "")
        if alias:
            alias_to_table[alias] = name

    out: list[tuple[str, str, str, str]] = []
    for node in tree.find_all(exp.EQ):
        left, right = node.left, node.right
        col = (
            left
            if isinstance(left, exp.Column)
            else right
            if isinstance(right, exp.Column)
            else None
        )
        other = right if col is left else left if col is right else None
        if col is None or other is None or isinstance(other, exp.Column):
            continue
        col_name = _norm(col.name or "")
        table_ref = _norm(col.table or "")
        table = alias_to_table.get(table_ref, table_ref)
        param = _param_label(other)
        if param is not None:
            out.append((table, col_name, "bind", param))
            continue
        if isinstance(other, (exp.Literal, exp.Boolean)):
            out.append((table, col_name, "literal", str(other.this)))
            continue
        out.append((table, col_name, "expr", _render_expr(other, dialect)))
    return out


def _resolve_key(
    table: str,
    column: str,
    identity_keys: set[tuple[str, str]],
) -> tuple[str, str]:
    key = (_norm(table), _norm(column))
    if key in identity_keys:
        return key
    if not key[0] and identity_keys:
        matches = [t for t, c in identity_keys if c == key[1]]
        if len(set(matches)) == 1:
            return (matches[0], key[1])
    return key


def ungrounded_key_filters(
    sql: str,
    *,
    question: str,
    extra_text: str = "",
    identity_keys: set[tuple[str, str]] | None = None,
    dialect: str = "postgres",
) -> list[MissingSlot]:
    """PK/FK filters whose RHS was not supplied by the user.

    Binds are always ungrounded: this runner cannot fill parameters.
    """
    if not (sql or "").strip():
        return []
    keys = identity_keys or set()
    haystack = grounded_text(question, extra_text)
    binds = find_bind_placeholders(sql)
    missing: list[MissingSlot] = []
    seen: set[tuple[str, str, str]] = set()

    for table, column, kind, value in _eq_filters(sql, dialect):
        resolved = _resolve_key(table, column, keys)
        is_key = resolved in keys
        invented = False
        if kind == "bind":
            invented = True
        elif kind == "expr" and is_key:
            invented = True
        elif kind == "literal" and is_key and not literal_is_grounded(value, haystack):
            invented = True
        if not invented:
            continue
        item = MissingSlot(resolved[0] or "query", resolved[1] or "parameter", value)
        stamp = (item.table, item.column, item.used_value)
        if stamp not in seen:
            seen.add(stamp)
            missing.append(item)

    if not missing and binds:
        missing.append(MissingSlot("query", "parameter", binds[0]))
    return missing


def clarification_for_slots(slots: list[MissingSlot]) -> tuple[str, list[str]]:
    if not slots:
        return "", []
    slot = slots[0]
    if slot.table in {"query", "_", "?"} or slot.column in {"parameter", "_", "?"}:
        reason = (
            f"Query uses unbound parameter {slot.used_value}; "
            "this runner cannot bind values that are not in the question"
        )
        options = [
            "Name the person or account in the question",
            "Give an id or email that exists in the data",
            "Ask for every matching row (no single-row filter)",
        ]
        return reason, options
    reason = (
        f"Query filters {slot.table}.{slot.column}={slot.used_value} "
        "but that value is not in the question, history, or a business rule"
    )
    options = [
        f"Give a value for {slot.table}.{slot.column}",
        f"List {slot.table} so I can pick one",
        f"Run this for every {slot.table} (no single-row filter)",
    ]
    return reason, options


def ambiguity_from_slots(slots: list[MissingSlot]) -> dict:
    reason, options = clarification_for_slots(slots)
    return {
        "should_clarify": True,
        "reason": reason,
        "options": options,
        "source": "ungrounded_identity",
        "slots": [
            {
                "table": slot.table,
                "column": slot.column,
                "used_value": slot.used_value,
            }
            for slot in slots
        ],
    }


def _grounding_text(state: dict) -> str:
    context = state.get("context") or {}
    parts = [
        state.get("question") or "",
        context.get("business_rules") or "",
    ]
    for turn in state.get("conversation_history") or []:
        if not isinstance(turn, dict):
            continue
        parts.append(str(turn.get("question") or ""))
        parts.append(str(turn.get("sql") or ""))
        parts.append(str(turn.get("answer") or ""))
    return "\n".join(parts)


def _clarify_update(state: dict, sql: str, slots: list[MissingSlot]) -> dict:
    from src.agent.utils import append_step
    from src.agent.utils import max_retries

    ambiguity = ambiguity_from_slots(slots)
    return {
        "sql": sql,
        "corrected_sql": sql,
        "error": None,
        "intent": "CLARIFICATION_NEEDED",
        "intent_reason": ambiguity["reason"],
        "clarification_options": ambiguity["options"],
        "ambiguity": ambiguity,
        "retries": max_retries(),
        "steps": append_step(
            state,
            "missing_identity_slot",
            ambiguity["reason"],
            sql=sql,
            slots=ambiguity["slots"],
        ),
    }


def clarify_or_none(state: dict, sql: str, dialect: str = "postgres") -> dict | None:
    """Ask if a catalog-key filter is ungrounded. Never execute that SQL."""
    context = state.get("context") or {}
    keys = deserialize_keys(context.get("identity_keys"))
    slots = ungrounded_key_filters(
        sql,
        question=state.get("question") or "",
        extra_text=_grounding_text(state),
        identity_keys=keys,
        dialect=dialect,
    )
    if not slots:
        return None
    return _clarify_update(state, sql, slots)


def clarify_unbound(state: dict, sql: str, dialect: str = "postgres") -> dict:
    """Always ask — used when the driver rejected a bind we must not retry."""
    update = clarify_or_none(state, sql, dialect)
    if update is not None:
        return update
    binds = find_bind_placeholders(sql)
    token = binds[0] if binds else "$1"
    return _clarify_update(
        state, sql, [MissingSlot("query", "parameter", token)]
    )
