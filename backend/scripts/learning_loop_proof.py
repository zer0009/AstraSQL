#!/usr/bin/env python3
"""Replay a small question set after recording conventions from failures.

Usage:
  uv run python scripts/learning_loop_proof.py \\
    --from-report eval/results/run100.json \\
    --limit 8 \\
    --max-cost 0.3 \\
    --out eval/results/learning-proof.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--from-report", required=True)
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--max-cost", type=float, default=0.3)
    p.add_argument("--out", default="eval/results/learning-proof.json")
    args = p.parse_args()

    report_path = Path(args.from_report)
    if not report_path.is_absolute():
        report_path = _BACKEND / report_path
    data = json.loads(report_path.read_text(encoding="utf-8"))
    fails = [
        q
        for q in data.get("questions") or []
        if q.get("result_match_values") is not True
    ][: args.limit]
    if not fails:
        print("No failures to replay")
        return 0

    from sqlalchemy import select

    from src.context.conventions import record_join_type_convention
    from src.context.learning_loop import record_reviewed_query
    from src.context.semantic_layer import parse_semantic_layer
    from src.eval.pilot import parse_args as pilot_parse, _run
    from src.storage.database import get_session_factory
    from src.storage.models import Connection

    # Seed conventions / reviewed gold from failure rows (gold SQL as teacher).
    factory = get_session_factory()
    async with factory() as session:
        for row in fails:
            db_id = row.get("db_id")
            name = f"spider-{db_id}"
            result = await session.execute(
                select(Connection).where(Connection.name == name)
            )
            conn = result.scalar_one_or_none()
            if conn is None:
                continue
            layer = parse_semantic_layer(conn.semantic_layer_json) or {}
            gold = str(row.get("gold_sql") or "")
            q = str(row.get("question") or "")
            if gold and q:
                layer = record_reviewed_query(layer, q, gold)
                layer = record_join_type_convention(layer, gold)
            conn.semantic_layer_json = json.dumps(layer)
        await session.commit()

    # Build a tiny from-report JSON of just the failures and re-run.
    subset = {
        "db_ids": sorted({r["db_id"] for r in fails}),
        "questions": fails,
    }
    subset_path = _BACKEND / "eval" / "results" / "_learning_subset.json"
    subset_path.parent.mkdir(parents=True, exist_ok=True)
    subset_path.write_text(json.dumps(subset, indent=2), encoding="utf-8")

    pilot_args = pilot_parse(
        [
            "--from-report",
            str(subset_path),
            "--max-cost",
            str(args.max_cost),
            "--out",
            args.out,
            "--concurrency",
            "1",
        ]
    )
    report = await _run(pilot_args)
    before = sum(1 for r in fails if r.get("result_match_values") is True)
    after = sum(
        1
        for r in report.get("questions") or []
        if r.get("result_match_values") is True
    )
    print(
        f"Learning proof: before={before}/{len(fails)} "
        f"after={after}/{len(report.get('questions') or [])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
