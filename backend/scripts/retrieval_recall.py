#!/usr/bin/env python3
"""Token-free retrieval / value-grounding recall against Spider/BIRD gold.

Usage (from backend/):
  uv run python scripts/retrieval_recall.py
  uv run python scripts/retrieval_recall.py --dataset spider --limit 50

No embeddings and no LLM. Skips missing benchmark data without failing hard.

For each gold question:
  - Extract gold tables from gold SQL (sqlglot).
  - If schema table count is under the full-schema token budget heuristic,
    mark recall=1.0 (full schema would be passed).
  - Otherwise use lexical table-name overlap against question tokens.
  - When a SQLite DB file exists, extract string literals from gold WHERE
    clauses and score ``match_literals_fuzzy`` against sampled distinct values.

Writes ``eval/results/retrieval_recall_report.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

RESULTS_DIR = _BACKEND / "eval" / "results"
REPORT_PATH = RESULTS_DIR / "retrieval_recall_report.json"
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _extract_tables(sql: str, dialect: str = "sqlite") -> set[str]:
    from src.eval.failure_labels import extract_tables

    return extract_tables(sql, dialect=dialect)


def _question_tokens(question: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(question or "")}


def _lexical_table_recall(gold_tables: set[str], question: str) -> float:
    if not gold_tables:
        return 1.0
    tokens = _question_tokens(question)
    if not tokens:
        return 0.0
    hit = 0
    for table in gold_tables:
        parts = {p for p in re.split(r"[_\s]+", table.lower()) if p}
        # Match full name or underscore parts against question tokens / substrings
        q_lower = (question or "").lower()
        if table.lower() in tokens or table.lower() in q_lower:
            hit += 1
            continue
        if parts and all(p in tokens or p in q_lower for p in parts):
            hit += 1
            continue
        # Soft: any part overlaps
        if any(p in tokens for p in parts if len(p) >= 3):
            hit += 1
    return hit / len(gold_tables)


def _list_sqlite_tables(db_path: Path) -> list[str]:
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            return [str(r[0]) for r in rows]
        finally:
            con.close()
    except Exception:
        return []


def _gold_string_literals(sql: str, dialect: str = "sqlite") -> list[str]:
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql, dialect=dialect)
        lit: list[str] = []
        for where in tree.find_all(exp.Where):
            for node in where.find_all(exp.Literal):
                if node.is_string:
                    text = str(node.this or "").strip()
                    if text:
                        lit.append(text)
        return lit
    except Exception:
        return [m.group(1) for m in re.finditer(r"'([^']+)'", sql or "")]


def _sample_value_index(db_path: Path, *, limit: int = 50) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except Exception:
        return index
    try:
        tables = _list_sqlite_tables(db_path)
        for table in tables:
            try:
                cols = con.execute(f'PRAGMA table_info("{table}")').fetchall()
            except Exception:
                continue
            for col in cols:
                col_name = str(col[1])
                col_type = str(col[2] or "").upper()
                if any(t in col_type for t in ("INT", "REAL", "BLOB", "NUMERIC")) and "CHAR" not in col_type and "TEXT" not in col_type:
                    # Still allow unknown / TEXT
                    if col_type and "TEXT" not in col_type and "CHAR" not in col_type and "CLOB" not in col_type:
                        continue
                try:
                    rows = con.execute(
                        f'SELECT DISTINCT "{col_name}" FROM "{table}" '
                        f'WHERE "{col_name}" IS NOT NULL LIMIT ?',
                        (limit,),
                    ).fetchall()
                except Exception:
                    continue
                values = [str(r[0]) for r in rows if r[0] is not None and str(r[0]).strip()]
                if values:
                    index[f"{table}.{col_name}"] = values
    finally:
        con.close()
    return index


def _load_spider_items(limit: Optional[int]) -> list[dict[str, Any]]:
    from src.eval.spider_data import DATA_DIR, db_sqlite_path, load_dev

    root = DATA_DIR / "spider_data"
    if not (root / "dev.json").exists():
        # try alternate
        for candidate in DATA_DIR.rglob("dev.json"):
            root = candidate.parent
            break
        else:
            print(f"Spider data missing under {DATA_DIR} — skipping spider.", file=sys.stderr)
            return []
    try:
        rows = load_dev(root)
    except Exception as exc:
        print(f"Failed to load Spider: {exc}", file=sys.stderr)
        return []
    items: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        if limit is not None and len(items) >= limit:
            break
        db_id = row.get("db_id") or ""
        try:
            db_path = db_sqlite_path(db_id, root)
        except FileNotFoundError:
            db_path = None
        items.append(
            {
                "id": f"spider:{db_id}:{i}",
                "dataset": "spider",
                "db_id": db_id,
                "question": row.get("question") or "",
                "gold_sql": row.get("query") or row.get("gold_sql") or "",
                "db_path": str(db_path) if db_path and db_path.exists() else None,
            }
        )
    return items


def _load_bird_items(limit: Optional[int]) -> list[dict[str, Any]]:
    try:
        from src.eval import bird_data
    except Exception as exc:
        print(f"BIRD module unavailable: {exc}", file=sys.stderr)
        return []
    data_root = getattr(bird_data, "DATA_DIR", None) or (
        _BACKEND / "eval" / "benchmarks" / "data" / "bird"
    )
    # Prefer a small JSON if present
    candidates = [
        Path(data_root) / "mini_dev_sqlite.json",
        Path(data_root) / "dev.json",
        Path(data_root) / "BIRD-mini-dev" / "mini_dev_sqlite.json",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        print(f"BIRD JSON missing under {data_root} — skipping bird.", file=sys.stderr)
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Failed to load BIRD: {exc}", file=sys.stderr)
        return []
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("items") or []
    items: list[dict[str, Any]] = []
    db_fn = getattr(bird_data, "db_sqlite_path", None)
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if limit is not None and len(items) >= limit:
            break
        db_id = row.get("db_id") or ""
        db_path = None
        if callable(db_fn):
            try:
                db_path = db_fn(db_id)
            except Exception:
                db_path = None
        items.append(
            {
                "id": f"bird:{db_id}:{i}",
                "dataset": "bird",
                "db_id": db_id,
                "question": row.get("question") or "",
                "gold_sql": row.get("SQL") or row.get("query") or row.get("gold_sql") or "",
                "db_path": str(db_path) if db_path and Path(db_path).exists() else None,
            }
        )
    return items


def evaluate_item(
    item: dict[str, Any],
    *,
    full_schema_table_budget: int = 40,
) -> dict[str, Any]:
    gold_sql = item.get("gold_sql") or ""
    question = item.get("question") or ""
    gold_tables = _extract_tables(gold_sql)
    db_path_raw = item.get("db_path")
    db_path = Path(db_path_raw) if db_path_raw else None
    schema_tables = _list_sqlite_tables(db_path) if db_path and db_path.exists() else []

    if schema_tables and len(schema_tables) <= full_schema_table_budget:
        mode = "full_schema"
        recall = 1.0
        selected = sorted(t.lower() for t in schema_tables)
    else:
        mode = "lexical"
        recall = _lexical_table_recall(gold_tables, question)
        # Approximate "selected" as tables whose names overlap the question
        tokens = _question_tokens(question)
        q_lower = question.lower()
        selected = sorted(
            t.lower()
            for t in (schema_tables or list(gold_tables))
            if t.lower() in tokens
            or t.lower() in q_lower
            or any(p in tokens for p in re.split(r"_+", t.lower()) if len(p) >= 3)
        )

    value_grounding: dict[str, Any] = {
        "literals": [],
        "hints": [],
        "hit_rate": None,
        "skipped": True,
    }
    if db_path and db_path.exists() and gold_sql:
        literals = _gold_string_literals(gold_sql)
        if literals:
            from src.context.value_grounding import match_literals_fuzzy

            index = _sample_value_index(db_path)
            hints = match_literals_fuzzy(literals, index) if index else []
            matched_lits = {h.get("literal") for h in hints}
            hit = sum(1 for lit in literals if lit in matched_lits)
            value_grounding = {
                "literals": literals,
                "hints": hints[:20],
                "hit_rate": (hit / len(literals)) if literals else None,
                "skipped": False,
                "index_keys": len(index),
            }
        else:
            value_grounding = {
                "literals": [],
                "hints": [],
                "hit_rate": None,
                "skipped": True,
                "reason": "no_string_literals",
            }

    return {
        "id": item.get("id"),
        "dataset": item.get("dataset"),
        "db_id": item.get("db_id"),
        "gold_tables": sorted(gold_tables),
        "schema_table_count": len(schema_tables),
        "mode": mode,
        "recall": recall,
        "selected_tables": selected,
        "value_grounding": value_grounding,
        "db_available": bool(db_path and db_path.exists()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        choices=("spider", "bird", "both"),
        default="both",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max items per dataset")
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    parser.add_argument(
        "--full-schema-tables",
        type=int,
        default=40,
        help="Table-count threshold treated as full-schema (recall=1.0)",
    )
    args = parser.parse_args(argv)

    items: list[dict[str, Any]] = []
    if args.dataset in ("spider", "both"):
        items.extend(_load_spider_items(args.limit))
    if args.dataset in ("bird", "both"):
        items.extend(_load_bird_items(args.limit))

    details = [
        evaluate_item(it, full_schema_table_budget=args.full_schema_tables) for it in items
    ]
    recalls = [d["recall"] for d in details if d.get("recall") is not None]
    vg_rates = [
        d["value_grounding"]["hit_rate"]
        for d in details
        if isinstance(d.get("value_grounding"), dict)
        and d["value_grounding"].get("hit_rate") is not None
    ]
    report = {
        "kind": "retrieval_recall",
        "n": len(details),
        "mean_recall": (sum(recalls) / len(recalls)) if recalls else None,
        "mean_value_grounding_hit_rate": (sum(vg_rates) / len(vg_rates)) if vg_rates else None,
        "full_schema_count": sum(1 for d in details if d.get("mode") == "full_schema"),
        "lexical_count": sum(1 for d in details if d.get("mode") == "lexical"),
        "details": details,
    }

    out_path: Path = args.out
    if not out_path.is_absolute():
        out_path = (_BACKEND / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"n={report['n']} mean_recall={report['mean_recall']} "
        f"vg_hit={report['mean_value_grounding_hit_rate']}"
    )
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
