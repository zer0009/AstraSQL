"""Rule-based failure labels for eval cases. No LLM."""

from __future__ import annotations

import re
from typing import Any

import sqlglot
from sqlglot import exp

from src.eval.compare import results_equal, results_equal_values

FailureLabel = str


def extract_tables(sql: str | None, dialect: str = "sqlite") -> set[str]:
    text = (sql or "").strip()
    if not text:
        return set()
    found: set[str] = set()
    try:
        for tree in sqlglot.parse(text, dialect=dialect):
            if tree is None:
                continue
            for table in tree.find_all(exp.Table):
                name = (table.name or "").strip().strip('"').lower()
                if name:
                    found.add(name)
    except Exception:
        # Fallback: crude FROM/JOIN tokens
        for match in re.finditer(
            r"\b(?:from|join)\s+([\"`]?)([A-Za-z_][\w]*)\1",
            text,
            flags=re.IGNORECASE,
        ):
            found.add(match.group(2).lower())
    return found


def _columns(sql: str | None, dialect: str = "sqlite") -> set[str]:
    text = (sql or "").strip()
    if not text:
        return set()
    found: set[str] = set()
    try:
        tree = sqlglot.parse_one(text, dialect=dialect)
        for col in tree.find_all(exp.Column):
            name = (col.name or "").strip().strip('"').lower()
            if name and name != "*":
                found.add(name)
    except Exception:
        pass
    return found


def _has_left_join(sql: str | None, dialect: str = "sqlite") -> bool:
    text = (sql or "").strip()
    if not text:
        return False
    if re.search(r"\bleft\s+(outer\s+)?join\b", text, re.IGNORECASE):
        return True
    try:
        tree = sqlglot.parse_one(text, dialect=dialect)
        for join in tree.find_all(exp.Join):
            kind = (join.side or "").upper()
            if kind == "LEFT":
                return True
    except Exception:
        pass
    return False


def _has_max_subquery(sql: str | None) -> bool:
    return bool(re.search(r"\bmax\s*\(", (sql or ""), re.IGNORECASE))


def _has_order_limit_subquery(sql: str | None) -> bool:
    text = (sql or "")
    return bool(
        re.search(r"\border\s+by\b[\s\S]{0,80}\blimit\s+\d+", text, re.IGNORECASE)
    )


def label_failure(
    *,
    question: str = "",
    gold_sql: str | None,
    generated_sql: str | None,
    gold_result: dict | None = None,
    generated_result: dict | None = None,
    clarified: bool = False,
    error: str | None = None,
    dialect: str = "sqlite",
) -> FailureLabel:
    """Return a single failure label for a non-matching case."""
    gen = (generated_sql or "").strip()
    gold = (gold_sql or "").strip()

    if clarified and not gen:
        return "clarified_instead_of_answering"
    if error and not gen:
        return "sql_error"
    if not gen:
        return "no_sql"
    if error:
        return "sql_error"

    strict_ok = False
    values_ok = False
    if gold_result is not None and generated_result is not None:
        strict_ok = results_equal(gold_result, generated_result)
        values_ok = results_equal_values(
            gold_result, generated_result, gold_sql=gold
        )
        if values_ok and not strict_ok:
            return "scorer_only"
        if values_ok and strict_ok:
            return "other"  # caller should not label passes

    gold_tables = extract_tables(gold, dialect)
    gen_tables = extract_tables(gen, dialect)
    if gold_tables and gen_tables:
        extra = gen_tables - gold_tables
        missing = gold_tables - gen_tables
        if extra and not missing:
            return "wrong_table"
        if missing and not extra:
            return "missing_table"
        if missing and extra:
            return "wrong_table"

    if gold_tables and gen_tables == gold_tables:
        gold_left = _has_left_join(gold, dialect)
        gen_left = _has_left_join(gen, dialect)
        if gold_left != gen_left:
            g_rows = int((gold_result or {}).get("row_count") or len((gold_result or {}).get("rows") or []))
            q_rows = int(
                (generated_result or {}).get("row_count")
                or len((generated_result or {}).get("rows") or [])
            )
            if g_rows != q_rows:
                return "join_type"

    if (_has_max_subquery(gen) and _has_order_limit_subquery(gold)) or (
        _has_max_subquery(gold) and _has_order_limit_subquery(gen)
    ):
        # Often still denotation-equal; if we are labelling a failure, flag it.
        if not values_ok:
            return "tie_or_limit"

    gold_cols = _columns(gold, dialect)
    gen_cols = _columns(gen, dialect)
    if gold_cols and gen_cols:
        if not (gold_cols & gen_cols) and gen_tables == gold_tables:
            return "wrong_column"
        # Same tables, overlapping columns — look at WHERE / GROUP
        if " group by " in gold.lower() or " group by " in gen.lower():
            if gold.lower().count("group by") != gen.lower().count("group by") or (
                ("count(" in gold.lower()) != ("count(" in gen.lower())
            ):
                return "aggregation_or_grouping"
        if " where " in gold.lower() or " where " in gen.lower():
            return "wrong_filter_or_value"

    if " join " in gold.lower() and " join " not in gen.lower():
        return "missing_join"

    if any(
        tok in gold.lower() or tok in gen.lower()
        for tok in (" group by ", " count(", " sum(", " avg(", " min(", " max(")
    ):
        return "aggregation_or_grouping"

    return "other"


def label_case(case: dict[str, Any], *, dialect: str = "sqlite") -> FailureLabel:
    """Label from a pilot/report case dict."""
    values_ok = case.get("result_match_values")
    strict_ok = case.get("result_match")
    if values_ok is True:
        if strict_ok is False:
            return "scorer_only"
        return "pass"
    return label_failure(
        question=str(case.get("question") or ""),
        gold_sql=case.get("gold_sql"),
        generated_sql=case.get("generated_sql"),
        gold_result=case.get("gold_result"),
        generated_result=case.get("generated_result"),
        clarified=bool(case.get("clarified")),
        error=case.get("error"),
        dialect=dialect,
    )
