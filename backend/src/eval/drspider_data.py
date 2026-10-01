"""Dr.Spider / Spider-Realistic loader stub.

Expected layout (set ``DRSPIDER_ROOT`` or pass ``root``)::

  eval/benchmarks/data/drspider/
    *.json                 # list of {question, query|SQL, db_id, ...}
    # or nested:
    Spider-Realistic/
      *.json

Returns GoldItem-compatible dicts::

  {"id", "question", "gold_sql", "expect": "answer", "tags", "db_id"?}

No automatic download — place files after accepting the dataset license.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
DATA_DIR = _BACKEND / "eval" / "benchmarks" / "data" / "drspider"


def drspider_root() -> Path:
    env = (os.environ.get("DRSPIDER_ROOT") or "").strip()
    return Path(env) if env else DATA_DIR


def drspider_available(root: Path | None = None) -> bool:
    base = root or drspider_root()
    if not base.is_dir():
        return False
    return any(base.rglob("*.json"))


def _to_gold(item: dict[str, Any], idx: int) -> dict[str, Any] | None:
    question = str(
        item.get("question")
        or item.get("utterance")
        or item.get("NL")
        or ""
    ).strip()
    if not question:
        return None
    sql = item.get("query") or item.get("SQL") or item.get("gold_sql") or item.get("sql")
    gold_sql = str(sql).strip() if sql else None
    db_id = item.get("db_id") or item.get("database") or item.get("db")
    case_id = str(item.get("id") or item.get("qid") or f"drspider-{idx}")
    tags = ["drspider"]
    if item.get("type"):
        tags.append(str(item["type"]))
    out: dict[str, Any] = {
        "id": case_id,
        "question": question,
        "gold_sql": gold_sql,
        "expect": "answer",
        "tags": tags,
    }
    if db_id:
        out["db_id"] = str(db_id)
    return out


def load_drspider(root: Path | None = None) -> list[dict[str, Any]]:
    """Load Dr.Spider / Spider-Realistic JSON if present; else raise FileNotFoundError."""
    base = root or drspider_root()
    if not base.exists():
        raise FileNotFoundError(
            f"Dr.Spider data not found at {base}. "
            "Set DRSPIDER_ROOT or place JSON under eval/benchmarks/data/drspider/."
        )
    paths = sorted(base.rglob("*.json"))
    if not paths:
        raise FileNotFoundError(f"No JSON files under {base}")

    gold: list[dict[str, Any]] = []
    idx = 0
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        items: list[Any]
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (
                data.get("data")
                or data.get("examples")
                or data.get("items")
                or []
            )
        else:
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            converted = _to_gold(item, idx)
            if converted:
                gold.append(converted)
                idx += 1
    if not gold:
        raise FileNotFoundError(f"No usable Dr.Spider examples under {base}")
    return gold
