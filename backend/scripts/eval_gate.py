#!/usr/bin/env python3
"""Release gate: compare a new report against a baseline with thresholds.

Usage:
  uv run python scripts/eval_gate.py \\
    --baseline eval/results/run25.json \\
    --candidate eval/results/run25-variance.json \\
    --min-accuracy-delta -0.02 \\
    --max-p95-latency-ratio 1.2 \\
    --max-cost-ratio 1.2

Exit code 0 = pass, 1 = fail. Suitable for nightly CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from src.eval.paired import compare_reports  # noqa: E402


def _p95(latencies: list[float]) -> float:
    if not latencies:
        return 0.0
    xs = sorted(latencies)
    idx = int(0.95 * (len(xs) - 1))
    return float(xs[idx])


def main() -> int:
    p = argparse.ArgumentParser(description="Eval release gate")
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument(
        "--min-accuracy-delta",
        type=float,
        default=-0.02,
        help="Fail if (acc_b - acc_a) is below this (default -2pp)",
    )
    p.add_argument(
        "--max-p95-latency-ratio",
        type=float,
        default=1.2,
        help="Fail if candidate p95 / baseline p95 exceeds this",
    )
    p.add_argument(
        "--max-cost-ratio",
        type=float,
        default=1.2,
        help="Fail if candidate avg cost / baseline avg cost exceeds this",
    )
    args = p.parse_args()

    base_path = Path(args.baseline)
    cand_path = Path(args.candidate)
    if not base_path.is_absolute():
        base_path = _BACKEND / base_path
    if not cand_path.is_absolute():
        cand_path = _BACKEND / cand_path

    a = json.loads(base_path.read_text(encoding="utf-8"))
    b = json.loads(cand_path.read_text(encoding="utf-8"))
    cmp = compare_reports(a, b)

    a_lats = [float(q.get("elapsed_ms") or 0) for q in a.get("questions") or []]
    b_lats = [float(q.get("elapsed_ms") or 0) for q in b.get("questions") or []]
    a_costs = [float(q.get("cost_usd") or 0) for q in a.get("questions") or []]
    b_costs = [float(q.get("cost_usd") or 0) for q in b.get("questions") or []]

    a_p95 = _p95(a_lats)
    b_p95 = _p95(b_lats)
    a_avg_cost = sum(a_costs) / len(a_costs) if a_costs else 0.0
    b_avg_cost = sum(b_costs) / len(b_costs) if b_costs else 0.0

    delta = cmp["b_accuracy"] - cmp["a_accuracy"]
    lat_ratio = (b_p95 / a_p95) if a_p95 > 0 else 0.0
    cost_ratio = (b_avg_cost / a_avg_cost) if a_avg_cost > 0 else 0.0

    failures: list[str] = []
    if delta < args.min_accuracy_delta:
        failures.append(
            f"accuracy delta {delta:.4f} < min {args.min_accuracy_delta}"
        )
    if a_p95 > 0 and lat_ratio > args.max_p95_latency_ratio:
        failures.append(
            f"p95 latency ratio {lat_ratio:.3f} > {args.max_p95_latency_ratio}"
        )
    if a_avg_cost > 0 and cost_ratio > args.max_cost_ratio:
        failures.append(
            f"cost ratio {cost_ratio:.3f} > {args.max_cost_ratio}"
        )

    print("======== EVAL GATE ========")
    print(f"baseline={base_path}")
    print(f"candidate={cand_path}")
    print(f"acc_a={cmp['a_accuracy']} acc_b={cmp['b_accuracy']} delta={delta:.4f}")
    print(f"p95_a={a_p95:.0f}ms p95_b={b_p95:.0f}ms ratio={lat_ratio:.3f}")
    print(f"avg_cost_a=${a_avg_cost:.6f} avg_cost_b=${b_avg_cost:.6f} ratio={cost_ratio:.3f}")
    print(f"mcnemar_p={cmp['mcnemar']['p_value']}")
    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        print("==========================")
        return 1
    print("PASS")
    print("==========================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
