#!/usr/bin/env python3
"""Classify gold vs generated SQL diffs from eval result JSON (no LLM).

Usage (from backend/):
  uv run python scripts/offline_sql_diff.py
  uv run python scripts/offline_sql_diff.py eval/results/held_out_merged20_v3.json

Writes ``eval/results/offline_diff_report.json`` and prints ranked counts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

RESULTS_DIR = _BACKEND / "eval" / "results"
DEFAULT_GLOBS = ("held_out*.json", "bird*.json")
REPORT_PATH = RESULTS_DIR / "offline_diff_report.json"

LABELS = (
    "missing_join",
    "wrong_aggregate",
    "wrong_literal",
    "extra_filter",
    "integer_division",
    "order_limit_mismatch",
    "cte_overengineering",
    "other",
)


def _load_questions(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"skip {path}: {exc}", file=sys.stderr)
        return []
    if isinstance(data, list):
        return [q for q in data if isinstance(q, dict)]
    if isinstance(data, dict):
        qs = data.get("questions") or data.get("cases") or data.get("items") or []
        return [q for q in qs if isinstance(q, dict)]
    return []


def _pred_sql(item: dict[str, Any]) -> Optional[str]:
    for key in ("generated_sql", "predicted_sql", "sql"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _tables(sql: str, dialect: str = "sqlite") -> set[str]:
    try:
        import sqlglot
        from sqlglot import exp

        found: set[str] = set()
        for tree in sqlglot.parse(sql, dialect=dialect):
            if tree is None:
                continue
            for table in tree.find_all(exp.Table):
                name = (table.name or "").strip().strip('"').lower()
                if name:
                    found.add(name)
        return found
    except Exception:
        return {
            m.group(1).lower()
            for m in re.finditer(
                r"\b(?:from|join)\s+[\"`]?([A-Za-z_][\w]*)",
                sql,
                flags=re.IGNORECASE,
            )
        }


def _join_count(sql: str, dialect: str = "sqlite") -> int:
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql, dialect=dialect)
        return sum(1 for _ in tree.find_all(exp.Join))
    except Exception:
        return len(re.findall(r"\bjoin\b", sql, flags=re.IGNORECASE))


def _agg_names(sql: str, dialect: str = "sqlite") -> set[str]:
    names: set[str] = set()
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql, dialect=dialect)
        for node in tree.find_all(exp.AggFunc, exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max):
            names.add(type(node).__name__.lower())
        for node in tree.find_all(exp.Anonymous):
            n = (node.name or "").lower()
            if n in {"count", "sum", "avg", "min", "max", "group_concat", "total"}:
                names.add(n)
    except Exception:
        for m in re.finditer(
            r"\b(count|sum|avg|min|max|group_concat|total)\s*\(",
            sql,
            flags=re.IGNORECASE,
        ):
            names.add(m.group(1).lower())
    return names


def _literals(sql: str, dialect: str = "sqlite") -> set[str]:
    lit: set[str] = set()
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql, dialect=dialect)
        for node in tree.find_all(exp.Literal):
            if node.is_string:
                lit.add(str(node.this))
            else:
                lit.add(str(node.this))
    except Exception:
        for m in re.finditer(r"'([^']*)'", sql):
            lit.add(m.group(1))
    return lit


def _where_count(sql: str, dialect: str = "sqlite") -> int:
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql, dialect=dialect)
        wheres = list(tree.find_all(exp.Where))
        if not wheres:
            return 0
        # Count top-level AND/OR predicates roughly via comparisons under WHERE
        n = 0
        for w in wheres:
            n += sum(
                1
                for _ in w.find_all(
                    exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Like, exp.In
                )
            )
        return n
    except Exception:
        return 1 if re.search(r"\bwhere\b", sql, re.IGNORECASE) else 0


def _has_div(sql: str, dialect: str = "sqlite") -> bool:
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql, dialect=dialect)
        return any(True for _ in tree.find_all(exp.Div))
    except Exception:
        return "/" in sql


def _order_limit(sql: str) -> tuple[bool, bool]:
    text = sql or ""
    return (
        bool(re.search(r"\border\s+by\b", text, re.IGNORECASE)),
        bool(re.search(r"\blimit\b", text, re.IGNORECASE)),
    )


def _has_cte(sql: str, dialect: str = "sqlite") -> bool:
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql, dialect=dialect)
        return any(True for _ in tree.find_all(exp.CTE, exp.With))
    except Exception:
        return bool(re.search(r"\bwith\b", sql, re.IGNORECASE))


def classify_diff(gold_sql: str, pred_sql: str, dialect: str = "sqlite") -> str:
    """Return a single primary difference label."""
    g, p = gold_sql.strip(), pred_sql.strip()
    if not g or not p:
        return "other"

    g_tables, p_tables = _tables(g, dialect), _tables(p, dialect)
    g_joins, p_joins = _join_count(g, dialect), _join_count(p, dialect)
    if (g_tables - p_tables) or (g_joins > p_joins):
        return "missing_join"

    g_aggs, p_aggs = _agg_names(g, dialect), _agg_names(p, dialect)
    if g_aggs != p_aggs and (g_aggs or p_aggs):
        return "wrong_aggregate"

    g_lits, p_lits = _literals(g, dialect), _literals(p, dialect)
    if g_lits != p_lits and (g_lits or p_lits):
        # Prefer wrong_literal when string/numeric constants differ
        if (g_lits - p_lits) or (p_lits - g_lits):
            return "wrong_literal"

    g_where, p_where = _where_count(g, dialect), _where_count(p, dialect)
    if p_where > g_where:
        return "extra_filter"

    if _has_div(g, dialect) != _has_div(p, dialect) or (
        _has_div(g, dialect)
        and ("cast" in g.lower()) != ("cast" in p.lower())
        and ("real" in g.lower() or "real" in p.lower() or "/" in g or "/" in p)
    ):
        if _has_div(g, dialect) or _has_div(p, dialect):
            # Integer division mismatch when one side casts / other does not
            g_cast = "cast" in g.lower() and "real" in g.lower()
            p_cast = "cast" in p.lower() and "real" in p.lower()
            if g_cast != p_cast or ("/" in g) != ("/" in p):
                return "integer_division"

    g_ord, g_lim = _order_limit(g)
    p_ord, p_lim = _order_limit(p)
    if (g_ord, g_lim) != (p_ord, p_lim):
        return "order_limit_mismatch"

    if _has_cte(p, dialect) and not _has_cte(g, dialect):
        return "cte_overengineering"

    return "other"


def resolve_inputs(cli_paths: list[str]) -> list[Path]:
    if cli_paths:
        out: list[Path] = []
        for raw in cli_paths:
            path = Path(raw)
            if not path.is_absolute():
                path = (_BACKEND / path).resolve() if not path.exists() else path.resolve()
            if path.exists():
                out.append(path)
            else:
                print(f"missing file (skipped): {path}", file=sys.stderr)
        return out

    found: list[Path] = []
    for pattern in DEFAULT_GLOBS:
        found.extend(sorted(RESULTS_DIR.glob(pattern)))
    # Dedupe while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in found:
        if p in seen:
            continue
        seen.add(p)
        unique.append(p)
    return unique


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Result JSON files (default: held_out*.json and bird*.json)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPORT_PATH,
        help=f"Report path (default: {REPORT_PATH})",
    )
    args = parser.parse_args(argv)

    inputs = resolve_inputs(list(args.paths))
    if not inputs:
        print("No result files found; writing empty report.", file=sys.stderr)

    counts: Counter[str] = Counter()
    details: list[dict[str, Any]] = []
    skipped_equal = 0
    skipped_missing = 0

    for path in inputs:
        for item in _load_questions(path):
            gold = (item.get("gold_sql") or "").strip()
            pred = _pred_sql(item) or ""
            if not gold or not pred:
                skipped_missing += 1
                continue
            # Only mine mismatches (or always classify — classify all non-identical)
            from src.agent.trust import normalize_sql

            try:
                same = normalize_sql(gold, dialect="sqlite") == normalize_sql(
                    pred, dialect="sqlite"
                )
            except Exception:
                same = gold.strip().lower() == pred.strip().lower()
            if same or item.get("result_match_values") is True or item.get("sql_match") is True:
                skipped_equal += 1
                continue
            label = classify_diff(gold, pred)
            counts[label] += 1
            details.append(
                {
                    "source": str(path.name),
                    "id": item.get("id"),
                    "db_id": item.get("db_id"),
                    "label": label,
                    "gold_sql": gold,
                    "generated_sql": pred,
                }
            )

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    report = {
        "kind": "offline_sql_diff",
        "inputs": [str(p) for p in inputs],
        "counts": {k: counts.get(k, 0) for k in LABELS},
        "ranked": [{"label": k, "count": v} for k, v in ranked],
        "skipped_equal_or_match": skipped_equal,
        "skipped_missing_sql": skipped_missing,
        "n_classified": sum(counts.values()),
        "details": details,
    }

    out_path: Path = args.out
    if not out_path.is_absolute():
        out_path = (_BACKEND / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("Offline SQL diff labels (ranked):")
    if ranked:
        for label, n in ranked:
            print(f"  {n:5d}  {label}")
    else:
        print("  (none)")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
