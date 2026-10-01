"""Paired significance tests between two eval reports. No LLM."""

from __future__ import annotations

import math
import random
from typing import Any, Optional


def _values_ok(row: dict[str, Any]) -> bool:
    return row.get("result_match_values") is True


def mcnemar_exact(
    a_by_id: dict[str, bool],
    b_by_id: dict[str, bool],
) -> dict[str, Any]:
    """McNemar exact binomial test on discordant pairs (b vs a improvement).

    Contigency of paired outcomes:
      b01 = a correct, b wrong
      b10 = a wrong, b correct
    Two-sided p-value from exact binomial under p=0.5.
    """
    ids = sorted(set(a_by_id) & set(b_by_id))
    b01 = 0
    b10 = 0
    both_ok = 0
    both_fail = 0
    for i in ids:
        a_ok = bool(a_by_id[i])
        b_ok = bool(b_by_id[i])
        if a_ok and b_ok:
            both_ok += 1
        elif not a_ok and not b_ok:
            both_fail += 1
        elif a_ok and not b_ok:
            b01 += 1
        else:
            b10 += 1

    n_disc = b01 + b10
    if n_disc == 0:
        p_value = 1.0
    else:
        # Exact two-sided: sum Binomial(n, 0.5) probs as extreme as observed.
        k = min(b01, b10)
        # P(X <= k) * 2, capped at 1; use cumulative binomial.
        p_one = _binom_cdf(k, n_disc, 0.5)
        p_value = min(1.0, 2.0 * p_one)

    return {
        "n_paired": len(ids),
        "both_correct": both_ok,
        "both_wrong": both_fail,
        "a_only": b01,
        "b_only": b10,
        "discordant": n_disc,
        "p_value": round(p_value, 6),
        "significant_0_05": p_value < 0.05,
        "b_minus_a_accuracy": round(
            (sum(1 for i in ids if b_by_id[i]) - sum(1 for i in ids if a_by_id[i]))
            / len(ids),
            4,
        )
        if ids
        else 0.0,
    }


def _binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    # Direct sum — n is small for Spider evals (discordant << 100).
    total = 0.0
    for i in range(k + 1):
        total += math.comb(n, i) * (p**i) * ((1 - p) ** (n - i))
    return total


def bootstrap_accuracy_diff(
    a_by_id: dict[str, bool],
    b_by_id: dict[str, bool],
    *,
    n_boot: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """Paired bootstrap 95% CI for (acc_b - acc_a)."""
    ids = sorted(set(a_by_id) & set(b_by_id))
    if not ids:
        return {"n_paired": 0, "mean_diff": 0.0, "ci95": [0.0, 0.0]}
    rng = random.Random(seed)
    diffs: list[float] = []
    n = len(ids)
    for _ in range(n_boot):
        sample = [ids[rng.randrange(n)] for _ in range(n)]
        acc_a = sum(1 for i in sample if a_by_id[i]) / n
        acc_b = sum(1 for i in sample if b_by_id[i]) / n
        diffs.append(acc_b - acc_a)
    diffs.sort()
    lo = diffs[int(0.025 * n_boot)]
    hi = diffs[int(0.975 * n_boot)]
    mean = sum(diffs) / len(diffs)
    return {
        "n_paired": n,
        "n_boot": n_boot,
        "mean_diff": round(mean, 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "ci_excludes_zero": not (lo <= 0.0 <= hi),
    }


def compare_reports(
    report_a: dict[str, Any],
    report_b: dict[str, Any],
    *,
    key: str = "result_match_values",
) -> dict[str, Any]:
    """Compare two pilot/report JSON dicts by question id."""

    def _index(report: dict[str, Any]) -> dict[str, bool]:
        out: dict[str, bool] = {}
        for row in report.get("questions") or []:
            qid = str(row.get("id") or "")
            if not qid:
                continue
            if key == "result_match_values":
                out[qid] = _values_ok(row)
            elif key == "result_match_lenient":
                out[qid] = row.get("result_match_lenient") is True
            else:
                out[qid] = row.get(key) is True
        return out

    a = _index(report_a)
    b = _index(report_b)
    mcn = mcnemar_exact(a, b)
    boot = bootstrap_accuracy_diff(a, b)
    flips = sorted(
        i for i in set(a) & set(b) if a[i] != b[i]
    )
    return {
        "key": key,
        "mcnemar": mcn,
        "bootstrap": boot,
        "flips": [
            {
                "id": i,
                "a": a[i],
                "b": b[i],
            }
            for i in flips
        ],
        "a_accuracy": round(sum(a.values()) / len(a), 4) if a else 0.0,
        "b_accuracy": round(sum(b.values()) / len(b), 4) if b else 0.0,
        "a_path": report_a.get("out_path") or report_a.get("kind"),
        "b_path": report_b.get("out_path") or report_b.get("kind"),
    }
