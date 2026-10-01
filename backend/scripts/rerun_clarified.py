"""Re-run only the clarified questions from a prior pilot report (Phase 0)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


async def main() -> int:
    from src.eval.pilot import _run

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--from-report",
        default="eval/results/run50.json",
        help="Prior report JSON (default: eval/results/run50.json)",
    )
    p.add_argument("--model", default="gpt-5.6-luna")
    p.add_argument("--reasoning-effort", default="low")
    p.add_argument("--interpretation-mode", default="on")
    p.add_argument("--validator-mode", default="deterministic")
    p.add_argument("--out", default="eval/results/clarify-diag.json")
    p.add_argument("--max-cost", type=float, default=0.5)
    args = p.parse_args()

    report_path = Path(args.from_report)
    if not report_path.is_absolute():
        report_path = _BACKEND / report_path
    report = json.loads(report_path.read_text(encoding="utf-8"))
    clarified_ids = [
        q["id"] for q in report.get("questions") or [] if q.get("clarified")
    ]
    if not clarified_ids:
        print("No clarified questions in report")
        return 1

    # Write a slim report for --from-report reuse (pilot expects full question rows).
    slim = {
        "questions": [
            q for q in report["questions"] if q.get("id") in set(clarified_ids)
        ]
    }
    slim_path = _BACKEND / "eval" / "results" / "_clarify_subset.json"
    slim_path.parent.mkdir(parents=True, exist_ok=True)
    slim_path.write_text(json.dumps(slim), encoding="utf-8")

    ns = argparse.Namespace(
        download_only=False,
        force_download=False,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        interpretation_mode=args.interpretation_mode,
        validator_mode=args.validator_mode,
        schema_link_mode="",
        format_response=False,
        sql_candidate_count=None,
        execution_evidence_gate=None,
        merge_interpret_generate=None,
        from_report=str(slim_path),
        n=len(clarified_ids),
        db="",
        dbs=0,
        per_db=0,
        db_ids="",
        seed=42,
        max_cost=args.max_cost,
        out=args.out,
        command="run",
    )
    print(f"Re-running {len(clarified_ids)} clarified questions -> {args.out}")
    await _run(ns)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = _BACKEND / out_path
    if out_path.exists():
        result = json.loads(out_path.read_text(encoding="utf-8"))
        for q in result.get("questions") or []:
            amb = q.get("ambiguity") or {}
            print(
                f"{q.get('id')}: clarified={q.get('clarified')} "
                f"status={amb.get('status')} why={amb.get('decision_why')} "
                f"proposal={amb.get('proposal_status')} "
                f"cands={len(amb.get('candidates') or [])}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
