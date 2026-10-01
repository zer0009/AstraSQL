"""Deep-dive run100 failures and cost/latency by decision path."""

from __future__ import annotations

import json
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
r = json.loads((_BACKEND / "eval/results/run100.json").read_text(encoding="utf-8"))
qs = r["questions"]

print("=== REAL MISSES (not values-correct, not clarify) ===")
for q in qs:
    if q.get("result_match_values") is True:
        continue
    if q.get("clarified"):
        continue
    amb = q.get("ambiguity") or {}
    gold = (q.get("gold_sql") or "")[:120]
    gen = (q.get("generated_sql") or "")[:120]
    print(
        f"{q['id']} [{q.get('failure_label')}] hard={q.get('hardness')} "
        f"ms={q.get('elapsed_ms')} cost=${q.get('cost_usd'):.4f}"
    )
    print(f"  Q: {str(q.get('question') or '')[:100]}")
    print(f"  why={amb.get('decision_why')} status={amb.get('status')}")
    print(f"  gold: {gold}")
    print(f"  gen:  {gen}")
    print()

paths: dict[str, dict] = {}
for q in qs:
    why = str((q.get("ambiguity") or {}).get("decision_why") or "none")
    key = "execution_gate" if "execution_gate" in why else why.split(";")[0]
    bucket = paths.setdefault(
        key, {"n": 0, "ms": 0.0, "cost": 0.0, "calls": 0, "ok": 0, "in": 0, "out": 0}
    )
    bucket["n"] += 1
    bucket["ms"] += q.get("elapsed_ms") or 0
    bucket["cost"] += q.get("cost_usd") or 0
    bucket["calls"] += q.get("calls") or 0
    bucket["in"] += q.get("input_tokens") or 0
    bucket["out"] += q.get("output_tokens") or 0
    if q.get("result_match_values") is True:
        bucket["ok"] += 1

print("=== BY DECISION PATH ===")
for k, v in sorted(paths.items(), key=lambda kv: -kv[1]["cost"]):
    n = v["n"]
    print(
        f"{k:22s} n={n:3d} ok={v['ok']}/{n} "
        f"avg_ms={v['ms']/n:.0f} avg_cost=${v['cost']/n:.4f} "
        f"avg_calls={v['calls']/n:.1f} avg_tok_in={v['in']/n:.0f}"
    )

print("\n=== STAGE WALL TIME / COST ===")
for name in (
    "intent_classifier",
    "interpretation_resolver",
    "query_generator",
    "ambiguity_gate",
    "direct_response",
):
    info = (r.get("by_stage") or {}).get(name) or {}
    print(
        f"{name:28s} calls={info.get('calls')} "
        f"cost=${float(info.get('cost_usd') or 0):.4f} "
        f"wall_s={float(info.get('latency_ms') or 0)/1000:.1f} "
        f"in={info.get('input_tokens')} out={info.get('output_tokens')}"
    )

# Savings: clear path vs gate path
clear = paths.get("clear") or paths.get("clear;candidates=1")
# keys may be 'clear' from split
clear_n = sum(v["n"] for k, v in paths.items() if k.startswith("clear"))
gate = paths.get("execution_gate")
print("\n=== SAVINGS LEVERS (no accuracy drop) ===")
print(
    "- Intent classifier: 100 calls, ~590s wall, only $0.01 — parallelize with retrieval "
    "(PARALLEL_INTENT_RETRIEVAL needs Annotated reducers)."
)
print(
    "- Interpretation resolver: ~99 calls, $0.048, ~359s — enable MERGE_INTERPRET_GENERATE "
    "to skip on clear questions (56 already clear)."
)
if gate:
    print(
        f"- Ambiguity gate: {gate['n']} questions, ${gate['cost']:.4f}, "
        f"avg {gate['ms']/gate['n']:.0f}ms — skip sampling when resolver status=clear "
        f"and needs_execution_gate=false (already mostly done; {gate['n']} still sampled)."
    )
print(
    "- Scorer_only=27: values match but column names differ — not accuracy bugs; "
    "use values/lenient as primary gate metric."
)
print(
    f"- Remaining real SQL misses: "
    f"{sum(1 for q in qs if q.get('result_match_values') is not True and not q.get('clarified'))} "
    f"(table/join/filter/agg) — next accuracy work."
)
