"""Compare run50 vs run25 baselines. No LLM."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "results"


def summarize(r: dict, name: str) -> None:
    a = r["accuracy"]["overall"]
    t = r["totals"]
    n = t["n"]
    qs = r["questions"]
    times = [q["elapsed_ms"] for q in qs]
    costs = [q["cost_usd"] for q in qs]
    times_s = sorted(times)
    p50 = times_s[len(times_s) // 2] if times_s else 0
    p95 = times_s[int(0.95 * (len(times_s) - 1))] if times_s else 0
    clarified = sum(1 for q in qs if q.get("clarified"))
    labels = Counter(
        q.get("failure_label") or "pass"
        for q in qs
        if q.get("result_match_values") is not True
    )
    by_stage = r.get("by_stage") or {}
    print(f"==== {name} ====")
    print(f"n={n} dbs={r.get('db_ids')}")
    print(f"models={r.get('models')}")
    va = 100 * float(a.get("values_accuracy") or 0)
    la = 100 * float(a.get("lenient_accuracy") or 0)
    sa = 100 * float(a.get("strict_accuracy") or 0)
    print(f"values={a.get('values_correct')}/{n} ({va:.1f}%)")
    print(f"lenient={a.get('lenient_correct', 'n/a')}/{n} ({la:.1f}%)")
    print(f"strict={a.get('strict_correct')}/{n} ({sa:.1f}%)")
    print(f"schema_linking={r['accuracy'].get('schema_linking_recall')}")
    print(f"clarify_rate={clarified}/{n} ({100 * clarified / n:.1f}%)")
    print(f"cost_total=${t.get('cost_usd'):.4f} avg=${sum(costs) / n:.4f}")
    print(
        f"time_total={t.get('elapsed_ms') / 1000:.1f}s "
        f"avg={sum(times) / n / 1000:.1f}s "
        f"p50={p50 / 1000:.1f}s p95={p95 / 1000:.1f}s"
    )
    print(
        f"tokens in={t.get('input_tokens')} out={t.get('output_tokens')} "
        f"reason={t.get('reasoning_tokens')} calls={t.get('calls')}"
    )
    print(
        f"avg_tokens_in={t.get('input_tokens') / n:.0f} "
        f"avg_out={t.get('output_tokens') / n:.0f} "
        f"avg_reason={t.get('reasoning_tokens') / n:.0f} "
        f"avg_calls={t.get('calls') / n:.1f}"
    )
    print(
        "by_hardness:",
        {
            k: f"{v['values_correct']}/{v['n']}"
            for k, v in r["accuracy"].get("by_hardness", {}).items()
        },
    )
    print(
        "by_db:",
        {
            k: f"{v['values_correct']}/{v['n']}"
            for k, v in r["accuracy"].get("by_database", {}).items()
        },
    )
    print("failure_labels:", dict(labels))
    print("by_stage:")
    for stage, b in by_stage.items():
        print(
            f"  {stage}: calls={b['calls']} in={b['input_tokens']} "
            f"out={b['output_tokens']} reason={b.get('reasoning_tokens', 0)} "
            f"cost=${b['cost_usd']:.4f} time={b['latency_ms'] / 1000:.1f}s"
        )
    print()


def show_failures(r: dict, limit: int = 12) -> None:
    print("==== Sample failures / scorer_only (run50) ====")
    shown = 0
    for q in r["questions"]:
        vok = q.get("result_match_values")
        sok = q.get("result_match")
        if vok is True and sok is True:
            continue
        print(f"\n[{q.get('failure_label')}] {q.get('id')}")
        print(f"  Q: {q.get('question')}")
        print(f"  values/strict/lenient: {vok}/{sok}/{q.get('result_match_lenient')}")
        print(f"  clarified={q.get('clarified')} retries={q.get('retries')}")
        print(f"  gold: {(q.get('gold_sql') or '')[:160]}")
        print(f"  gen : {(q.get('generated_sql') or '')[:160]}")
        print(
            f"  tokens in={q.get('input_tokens')} out={q.get('output_tokens')} "
            f"reason={q.get('reasoning_tokens')} "
            f"cost=${q.get('cost_usd'):.4f} time={q.get('elapsed_ms')}ms"
        )
        shown += 1
        if shown >= limit:
            break
    print()


def main() -> None:
    r50 = json.loads((RESULTS / "run50.json").read_text(encoding="utf-8"))
    r25 = json.loads((RESULTS / "run25.json").read_text(encoding="utf-8"))
    summarize(r25, "BASELINE run25 (old agent)")
    summarize(r50, "NEW run50 (roadmap agent)")

    ids25 = {q["id"] for q in r25["questions"]}
    ids50 = {q["id"] for q in r50["questions"]}
    overlap = ids25 & ids50
    print(f"Overlapping question IDs: {len(overlap)}")
    if overlap:
        m25 = {q["id"]: q.get("result_match_values") for q in r25["questions"]}
        m50 = {q["id"]: q.get("result_match_values") for q in r50["questions"]}
        a_ok = sum(1 for i in overlap if m25[i])
        b_ok = sum(1 for i in overlap if m50[i])
        print(f"On overlap: run25 {a_ok}/{len(overlap)} run50 {b_ok}/{len(overlap)}")
        flips = [i for i in overlap if m25[i] != m50[i]]
        for i in flips:
            print(f"  flip {i}: run25={m25[i]} -> run50={m50[i]}")
    print()
    show_failures(r50)


if __name__ == "__main__":
    main()
