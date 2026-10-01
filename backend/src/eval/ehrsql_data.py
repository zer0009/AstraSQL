"""EHRSQL-style loader.

Expected layout (set ``EHRSQL_ROOT`` or pass ``root``)::

  eval/benchmarks/data/ehrsql/
    *.json   # list of {question, sql|query, is_answerable, ...}

Unanswerable items map to ``expect: "clarify"`` (product asks rather than
hallucinating). Answerable items map to ``expect: "answer"``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
DATA_DIR = _BACKEND / "eval" / "benchmarks" / "data" / "ehrsql"


def ehrsql_root() -> Path:
    env = (os.environ.get("EHRSQL_ROOT") or "").strip()
    return Path(env) if env else DATA_DIR


def ehrsql_available(root: Path | None = None) -> bool:
    base = root or ehrsql_root()
    return base.is_dir() and any(base.glob("*.json"))


def load_ehrsql(root: Path | None = None) -> list[dict[str, Any]]:
    """Load EHRSQL-style JSON (question, sql, is_answerable)."""
    base = root or ehrsql_root()
    if not base.exists():
        raise FileNotFoundError(
            f"EHRSQL data not found at {base}. "
            "Set EHRSQL_ROOT or place JSON under eval/benchmarks/data/ehrsql/."
        )
    paths = sorted(base.glob("*.json"))
    if not paths:
        raise FileNotFoundError(f"No JSON under {base}")

    out: list[dict[str, Any]] = []
    idx = 0
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else (
            data.get("data") or data.get("examples") or data.get("items") or []
            if isinstance(data, dict)
            else []
        )
        for item in items:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or item.get("query") or "").strip()
            # Prefer dedicated NL field when query is SQL.
            if item.get("question"):
                question = str(item["question"]).strip()
            if not question:
                continue
            sql = item.get("sql") or item.get("SQL") or item.get("gold_sql")
            # When "query" is SQL (not the NL), don't overwrite question.
            if sql is None and item.get("query") and item.get("question"):
                sql = item.get("query")
            is_ans = item.get("is_answerable")
            if is_ans is None:
                is_ans = item.get("answerable", True)
            if isinstance(is_ans, str):
                answerable = is_ans.strip().lower() in ("1", "true", "yes")
            else:
                answerable = bool(is_ans)
            out.append(
                {
                    "id": str(item.get("id") or f"ehrsql-{idx}"),
                    "question": question,
                    "gold_sql": str(sql).strip() if sql else None,
                    "expect": "answer" if answerable else "clarify",
                    "is_answerable": answerable,
                    "tags": ["ehrsql"] + ([] if answerable else ["unanswerable"]),
                }
            )
            idx += 1
    if not out:
        raise FileNotFoundError(f"No usable EHRSQL examples under {base}")
    return out
