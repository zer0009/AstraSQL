"""Dataset-agnostic eval item adapters.

Each adapter yields a common item shape consumed by the pilot runner:

  question, db_id, db_path, gold_sql, evidence, difficulty, stable_id, meta
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class EvalItem:
    question: str
    db_id: str
    gold_sql: str
    db_path: Path | None = None
    evidence: str = ""
    difficulty: str = "unknown"
    stable_id: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_raw(self) -> dict[str, Any]:
        """Shape expected by pilot._select_questions / _score loop."""
        return {
            "db_id": self.db_id,
            "question": self.question,
            "query": self.gold_sql,
            "_hardness": self.difficulty,
            "_stable_id": self.stable_id,
            "_evidence": self.evidence,
            "_db_path": str(self.db_path) if self.db_path else "",
            "_meta": self.meta,
            "_split": self.meta.get("split", ""),
        }


def _stable(db_id: str, question: str, prefix: str = "") -> str:
    digest = hashlib.sha1(f"{db_id}::{question}".encode("utf-8")).hexdigest()[:12]
    base = f"{db_id}:{digest}"
    return f"{prefix}{base}" if prefix else base


def spider_items_to_eval(
    items: list[dict[str, Any]],
    *,
    root: Path | None = None,
) -> list[EvalItem]:
    from src.eval.spider_data import db_sqlite_path, infer_hardness, question_stable_id

    out: list[EvalItem] = []
    for raw in items:
        db_id = str(raw.get("db_id") or "")
        q = str(raw.get("question") or "")
        sql = str(raw.get("query") or "")
        hard = str(raw.get("_hardness") or infer_hardness(sql))
        path: Path | None = None
        if root is not None and db_id:
            try:
                path = db_sqlite_path(db_id, root)
            except FileNotFoundError:
                path = None
        out.append(
            EvalItem(
                question=q,
                db_id=db_id,
                gold_sql=sql,
                db_path=path,
                difficulty=hard,
                stable_id=str(raw.get("_stable_id") or question_stable_id(raw)),
                meta={"split": raw.get("_split") or "", "source": "spider"},
            )
        )
    return out


def bird_items_to_eval(
    items: list[dict[str, Any]],
    *,
    root: Path | None = None,
    include_evidence: bool = True,
) -> list[EvalItem]:
    from src.eval.bird_data import bird_db_path, bird_root

    base = root or bird_root()
    out: list[EvalItem] = []
    for raw in items:
        db_id = str(
            raw.get("db_id")
            or raw.get("db")
            or raw.get("selected_database")
            or ""
        )
        q = str(raw.get("question") or "")
        sql = str(
            raw.get("SQL")
            or raw.get("query")
            or raw.get("gold_sql")
            or raw.get("sol_sql")
            or ""
        )
        evidence = str(raw.get("evidence") or "") if include_evidence else ""
        difficulty = str(
            raw.get("difficulty")
            or raw.get("difficulty_tier")
            or "unknown"
        ).lower()
        path: Path | None = None
        try:
            path = bird_db_path(db_id, base)
        except FileNotFoundError:
            path = None
        out.append(
            EvalItem(
                question=q,
                db_id=db_id,
                gold_sql=sql,
                db_path=path,
                evidence=evidence,
                difficulty=difficulty,
                stable_id=_stable(db_id, q, prefix="bird:"),
                meta={
                    "source": "bird",
                    "include_evidence": include_evidence,
                    "question_id": raw.get("question_id") or raw.get("instance_id"),
                },
            )
        )
    return out
