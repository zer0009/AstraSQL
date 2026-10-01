"""Compare run100 vs run50/run25 and print actionable improvement signals."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    path = _BACKEND / "eval" / "results" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.1f}%" if d else "n/a"


def _summary(report: dict, label: str) -> dict:
    qs = report.get("questions") or []
    n = len(qs)
    clarified = sum(1 for q in qs if q.get("clarified"))
    answered = n - clarified
    strict = sum(1 for q in qs if q.get("result_match") is True)
    values = sum(1 for q in qs if q.get("result_match_values") is True)
    lenient = sum(1 for q in qs if q.get("result_match_lenient") is True)
    # Answered-only accuracy (excludes clarifies from denominator of "when it answers")
    ans_vals = sum(
        1
        for q in qs
        if not q.get("clarified") and q.get("result_match_values") is True
    )
    costs = [float(q.get("cost_usd") or 0) for q in qs]
    times = [int(q.get("elapsed_ms") or 0) for q in qs]
    tin = [int(q.get("input_tokens") or 0) for q in qs]
    tout = [int(q.get("output_tokens") or 0) for q in qs]
    calls = [int(q.get("calls") or 0) for q in qs]
    labels = Counter(q.get("failure_label") or "ok" for q in qs)
    by_hard = Counter()
    hard_ok = Counter()
    for q in qs:
        h = q.get("hardness") or "unknown"
        by_hard[h] += 1
        if q.get("result_match_values") is True:
            hard_ok[h] += 1
    by_db = {}
    for q in qs:
        db = q.get("db_id") or "?"
        by_db.setdefault(db, {"n": 0, "values": 0, "clarified": 0})
        by_db[db]["n"] += 1
        if q.get("result_match_values") is True:
            by_db[db]["values"] += 1
        if q.get("clarified"):
            by_db[db]["clarified"] += 1

    times_sorted = sorted(times)
    p50 = times_sorted[len(times_sorted) // 2] if times_sorted else 0
    p95 = times_sorted[int(0.95 * (len(times_sorted) - 1))] if times_sorted else 0

    stage = report.get("by_stage") or {}
    return {
        "label": label,
        "n": n,
        "strict": strict,
        "values": values,
        "lenient": lenient,
        "clarified": clarified,
        "answered": answered,
        "answered_values": ans_vals,
        "avg_cost": sum(costs) / n if n else 0,
        "total_cost": sum(costs),
        "avg_ms": sum(times) / n if n else 0,
        "p50_ms": p50,
        "p95_ms": p95,
        "avg_in": sum(tin) / n if n else 0,
        "avg_out": sum(tout) / n if n else 0,
        "avg_calls": sum(calls) / n if n else 0,
        "labels": labels,
        "by_hard": {h: (hard_ok[h], by_hard[h]) for h in sorted(by_hard)},
        "by_db": by_db,
        "by_stage": stage,
        "questions": qs,
    }


def _print_block(s: dict) -> None:
    n = s["n"]
    print(f"\n=== {s['label']} (n={n}) ===")
    print(
        f"values={s['values']}/{n} ({_pct(s['values'], n)})  "
        f"strict={s['strict']}/{n} ({_pct(s['strict'], n)})  "
        f"lenient={s['lenient']}/{n} ({_pct(s['lenient'], n)})"
    )
    print(
        f"clarify={s['clarified']}/{n} ({_pct(s['clarified'], n)})  "
        f"answered-accuracy={s['answered_values']}/{s['answered']} "
        f"({_pct(s['answered_values'], s['answered'])})"
    )
    print(
        f"avg_cost=${s['avg_cost']:.4f}  total=${s['total_cost']:.4f}  "
        f"avg_ms={s['avg_ms']:.0f}  p50={s['p50_ms']}  p95={s['p95_ms']}"
    )
    print(
        f"avg_tokens in/out={s['avg_in']:.0f}/{s['avg_out']:.0f}  "
        f"avg_calls={s['avg_calls']:.1f}"
    )
    print("failure_labels:", dict(s["labels"].most_common(12)))
    print("by_hardness:", {h: f"{ok}/{tot}" for h, (ok, tot) in s["by_hard"].items()})
    weak = sorted(
        s["by_db"].items(),
        key=lambda kv: (kv[1]["values"] / kv[1]["n"] if kv[1]["n"] else 0, -kv[1]["clarified"]),
    )
    print("weakest_dbs:")
    for db, st in weak[:5]:
        print(
            f"  {db}: {st['values']}/{st['n']} values, "
            f"clarified={st['clarified']}"
        )


def _stage_table(s: dict) -> None:
    stage = s.get("by_stage") or {}
    if not stage:
        print("(no by_stage)")
        return
    print(f"\n--- stage costs ({s['label']}) ---")
    rows = []
    for name, info in stage.items():
        if not isinstance(info, dict):
            continue
        rows.append(
            (
                name,
                int(info.get("calls") or 0),
                float(info.get("cost_usd") or 0),
                float(info.get("latency_ms") or info.get("elapsed_ms") or 0),
                int(info.get("input_tokens") or 0),
                int(info.get("output_tokens") or 0),
            )
        )
    rows.sort(key=lambda r: -r[2])
    for name, calls, cost, ms, tin, tout in rows[:12]:
        print(
            f"  {name:28s} calls={calls:4d}  ${cost:.4f}  "
            f"{ms/1000:.1f}s  tok={tin}/{tout}"
        )


def _ambiguity_diag(s: dict) -> None:
    qs = s["questions"]
    clar = [q for q in qs if q.get("clarified")]
    print(f"\n--- clarify diagnostics ({s['label']}: {len(clar)}) ---")
    why = Counter()
    status = Counter()
    for q in clar:
        amb = q.get("ambiguity") or {}
        why[str(amb.get("decision_why") or "?")[:80]] += 1
        status[str(amb.get("status") or "?")] += 1
        print(
            f"  {q.get('id')}: status={amb.get('status')} "
            f"why={amb.get('decision_why')} "
            f"Q={str(q.get('question') or '')[:70]}"
        )
    if why:
        print("why_counts:", dict(why.most_common(8)))
    if status:
        print("status_counts:", dict(status))


def _overlap(a: dict, b: dict) -> None:
    """Paired stats on shared question ids."""
    qa = {q["id"]: q for q in a["questions"]}
    qb = {q["id"]: q for q in b["questions"]}
    shared = sorted(set(qa) & set(qb))
    if not shared:
        print("\n(no overlapping question ids for paired compare)")
        return
    a_ok = sum(1 for i in shared if qa[i].get("result_match_values") is True)
    b_ok = sum(1 for i in shared if qb[i].get("result_match_values") is True)
    a_cl = sum(1 for i in shared if qa[i].get("clarified"))
    b_cl = sum(1 for i in shared if qb[i].get("clarified"))
    gained = [
        i
        for i in shared
        if qa[i].get("result_match_values") is not True
        and qb[i].get("result_match_values") is True
    ]
    lost = [
        i
        for i in shared
        if qa[i].get("result_match_values") is True
        and qb[i].get("result_match_values") is not True
    ]
    print(f"\n=== paired overlap n={len(shared)} ({a['label']} -> {b['label']}) ===")
    print(
        f"values {a_ok}/{len(shared)} -> {b_ok}/{len(shared)}  "
        f"diff={b_ok - a_ok:+d}"
    )
    print(
        f"clarify {a_cl}/{len(shared)} -> {b_cl}/{len(shared)}  "
        f"diff={b_cl - a_cl:+d}"
    )
    print(f"gained={len(gained)} lost={len(lost)}")
    for i in gained[:5]:
        print(f"  + {i}: was clarified={qa[i].get('clarified')} now ok")
    for i in lost[:5]:
        print(
            f"  - {i}: now clarified={qb[i].get('clarified')} "
            f"label={qb[i].get('failure_label')}"
        )


def main() -> None:
    run100 = _summary(_load("run100.json"), "run100")
    run50 = _summary(_load("run50.json"), "run50")
    try:
        run25 = _summary(_load("run25.json"), "run25")
    except FileNotFoundError:
        run25 = None

    if run25:
        _print_block(run25)
    _print_block(run50)
    _print_block(run100)
    _stage_table(run100)
    _ambiguity_diag(run100)
    _overlap(run50, run100)

    # Token/time savings opportunities: stages that dominate when already correct
    qs = run100["questions"]
    correct = [q for q in qs if q.get("result_match_values") is True]
    if correct:
        print("\n--- cost on already-correct answers (savings opportunity) ---")
        print(
            f"n={len(correct)} avg_cost=${sum(q.get('cost_usd') or 0 for q in correct)/len(correct):.4f} "
            f"avg_ms={sum(q.get('elapsed_ms') or 0 for q in correct)/len(correct):.0f} "
            f"avg_calls={sum(q.get('calls') or 0 for q in correct)/len(correct):.1f}"
        )
        # How many correct answers still ran interpretation / gate
        with_gate = sum(
            1
            for q in correct
            if "execution_gate" in str((q.get("ambiguity") or {}).get("decision_why") or "")
            or (q.get("ambiguity") or {}).get("gate") == "execution_evidence"
        )
        print(f"correct answers that hit execution gate path: {with_gate}/{len(correct)}")

    out = {
        "run100": {k: v for k, v in run100.items() if k != "questions"},
        "run50": {k: v for k, v in run50.items() if k != "questions"},
    }
    out_path = _BACKEND / "eval" / "results" / "compare-run100.json"
    # Make counters JSON-serializable
    for block in out.values():
        if isinstance(block.get("labels"), Counter):
            block["labels"] = dict(block["labels"])
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
