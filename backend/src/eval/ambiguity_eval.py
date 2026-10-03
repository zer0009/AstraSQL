"""Ambiguity / ask-precision evaluation suite.

Primary runner for ``eval/benchmarks/must_clarify.json``. Prefer this module
over the Spider pilot for clarify-vs-answer scoring.

Examples::

  uv run python -m src.eval.ambiguity_eval
  uv run python -m src.eval.ambiguity_eval --bird-interact path/to/items.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
DEFAULT_MUST_CLARIFY = _BACKEND / "eval" / "benchmarks" / "must_clarify.json"

# Injected in tests; production imports run_query lazily.
RunQueryFn = Callable[..., Awaitable[Any]]


def must_clarify_path() -> Path:
    return DEFAULT_MUST_CLARIFY


def load_must_clarify(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Load product must-clarify items (expect=clarify|answer)."""
    p = Path(path) if path else must_clarify_path()
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"must_clarify JSON must be a list: {p}")
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question") or "").strip()
        if not q:
            continue
        expect = str(item.get("expect") or "clarify").strip().lower()
        if expect not in ("clarify", "answer"):
            expect = "clarify"
        out.append(
            {
                "id": str(item.get("id") or q[:48]),
                "question": q,
                "expect": expect,
                "tags": list(item.get("tags") or []),
                "reason": item.get("reason"),
            }
        )
    return out


def load_bird_interact_items(path: Path | str) -> list[dict[str, Any]]:
    """Load BIRD-Interact-Lite style items from a local JSON file.

    Expected fields (any of)::

      query / amb_user_query / user_query
      user_query_ambiguity (truthy → expect clarify)
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"BIRD-Interact file not found: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        items = raw.get("data") or raw.get("examples") or raw.get("items") or []
    else:
        items = raw
    if not isinstance(items, list):
        raise ValueError(f"Unexpected BIRD-Interact layout in {p}")

    out: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        question = (
            item.get("amb_user_query")
            or item.get("query")
            or item.get("user_query")
            or item.get("question")
            or ""
        )
        question = str(question).strip()
        if not question:
            continue
        amb = item.get("user_query_ambiguity")
        if amb is None:
            amb = item.get("ambiguity")
        if isinstance(amb, str):
            is_amb = amb.strip().lower() not in ("", "0", "false", "clear", "none")
        else:
            is_amb = bool(amb)
        out.append(
            {
                "id": str(item.get("id") or item.get("instance_id") or f"bird-interact-{i}"),
                "question": question,
                "expect": "clarify" if is_amb else "answer",
                "tags": ["bird-interact"],
                "raw_ambiguity": amb,
            }
        )
    return out


def state_was_clarified(state: Any) -> bool:
    """True when agent state indicates a clarification ask."""
    if not isinstance(state, dict):
        return False
    ambiguity = state.get("ambiguity")
    if isinstance(ambiguity, dict) and ambiguity.get("should_clarify"):
        return True
    intent = str(state.get("intent") or "").upper()
    if intent == "CLARIFICATION_NEEDED":
        return True
    options = state.get("clarification_options") or []
    if options and not (state.get("corrected_sql") or state.get("sql")):
        return True
    return False


def score_ask_precision_recall(
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score ask precision/recall from labeled outcomes.

    Each case: ``{"expect": "clarify"|"answer", "clarified": bool}``.

    - Clear questions (expect=answer) should **not** be clarified.
    - Ambiguous / must-clarify (expect=clarify) should be clarified.
    """
    tp = fp = tn = fn = 0
    for case in cases:
        expect = str(case.get("expect") or "").strip().lower()
        clarified = bool(case.get("clarified"))
        if expect == "clarify":
            if clarified:
                tp += 1
            else:
                fn += 1
        else:
            # expect answer (clear)
            if clarified:
                fp += 1
            else:
                tn += 1

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "n": len(cases),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


async def run_ambiguity_suite(
    items: list[dict[str, Any]],
    *,
    connection: Any,
    session: Any = None,
    run_query_fn: RunQueryFn | None = None,
) -> dict[str, Any]:
    """Run clarify/answer items through ``run_query`` (mockable).

    ``items`` entries: ``{id, question, expect: clarify|answer}``.
    """
    if run_query_fn is None:
        from src.agent.runner import run_query as run_query_fn  # type: ignore

    cases: list[dict[str, Any]] = []
    for item in items:
        question = str(item.get("question") or "").strip()
        expect = str(item.get("expect") or "clarify").strip().lower()
        case_id = str(item.get("id") or question[:48])
        if not question:
            continue
        error: str | None = None
        clarified = False
        try:
            state = await run_query_fn(session, connection, question)
            clarified = state_was_clarified(state)
        except Exception as exc:  # noqa: BLE001 — suite continues
            error = str(exc)
        cases.append(
            {
                "id": case_id,
                "question": question,
                "expect": expect if expect in ("clarify", "answer") else "clarify",
                "clarified": clarified,
                "error": error,
            }
        )

    scores = score_ask_precision_recall(cases)
    return {"scores": scores, "cases": cases}


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ambiguity ask precision/recall")
    parser.add_argument(
        "--must-clarify",
        type=Path,
        default=None,
        help="Path to must_clarify.json (default: eval/benchmarks/must_clarify.json)",
    )
    parser.add_argument(
        "--bird-interact",
        type=Path,
        default=None,
        help="Optional local BIRD-Interact-Lite JSON path",
    )
    parser.add_argument(
        "--score-only",
        type=Path,
        default=None,
        help="Score a precomputed cases JSON (skip LLM); prints precision/recall",
    )
    args = parser.parse_args(argv)

    if args.score_only:
        cases = json.loads(args.score_only.read_text(encoding="utf-8"))
        if isinstance(cases, dict):
            cases = cases.get("cases") or []
        scores = score_ask_precision_recall(cases)
        print(json.dumps(scores, indent=2))
        return 0

    items = load_must_clarify(args.must_clarify)
    if args.bird_interact:
        items.extend(load_bird_interact_items(args.bird_interact))

    # Without a live Connection, emit the item list + empty scores for wiring checks.
    # Full suite: call run_ambiguity_suite from pilot/scripts with a Connection.
    print(
        json.dumps(
            {
                "n_items": len(items),
                "source": "must_clarify"
                + ("+bird_interact" if args.bird_interact else ""),
                "message": (
                    "Loaded items. Run run_ambiguity_suite(connection=...) "
                    "or pass --score-only with precomputed clarified flags."
                ),
                "precision": None,
                "recall": None,
                "items_preview": [
                    {"id": i["id"], "expect": i["expect"]} for i in items[:5]
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
