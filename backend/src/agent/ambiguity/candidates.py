"""Grounding, validation, and candidate option helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.agent.ambiguity.schema_digest import _norm_name, _split_table_column
from src.agent.ambiguity.types import (
    _MAX_LABEL_LEN,
    _MAX_OPTIONS,
    _OTHER_OPTION,
    InterpretationCandidate,
    InterpretationProposal,
    _content_tokens,
)


def candidate_is_grounded(
    candidate: InterpretationCandidate,
    *,
    tables: set[str],
    column_pairs: set[tuple[str, str]],
    bare_columns: set[str],
) -> bool:
    """True when every cited table/column exists in the retrieved schema."""
    if not candidate.tables and not candidate.columns:
        return False

    has_column_catalog = bool(column_pairs or bare_columns)

    for table in candidate.tables:
        if _norm_name(table) not in tables:
            return False

    for ref in candidate.columns:
        table, column = _split_table_column(ref)
        if not column:
            return False
        if table:
            if table not in tables:
                return False
            if not has_column_catalog:
                continue
            if (table, column) in column_pairs or column in bare_columns:
                continue
            return False
        # Bare column name
        if not has_column_catalog:
            continue
        if column in bare_columns or any(c == column for _, c in column_pairs):
            continue
        return False
    return True


def validate_candidates(
    candidates: Iterable[InterpretationCandidate],
    *,
    tables: set[str],
    column_pairs: set[tuple[str, str]],
    bare_columns: set[str],
) -> list[InterpretationCandidate]:
    valid: list[InterpretationCandidate] = []
    seen: set[str] = set()
    for raw in candidates:
        if not isinstance(raw, InterpretationCandidate):
            continue
        if not candidate_is_grounded(
            raw,
            tables=tables,
            column_pairs=column_pairs,
            bare_columns=bare_columns,
        ):
            continue
        question = (raw.question or "").strip()
        if not question:
            continue
        key = question.lower()
        if key in seen:
            continue
        seen.add(key)
        label = (raw.label or question).strip()
        if len(label) > _MAX_LABEL_LEN:
            label = label[: _MAX_LABEL_LEN - 1] + "…"
        valid.append(
            InterpretationCandidate(
                label=label,
                question=question,
                tables=tuple(_norm_name(t) for t in raw.tables if _norm_name(t)),
                columns=tuple(c.strip() for c in raw.columns if str(c).strip()),
            )
        )
        if len(valid) >= _MAX_OPTIONS:
            break
    return valid


def _options_from_candidates(
    candidates: list[InterpretationCandidate],
    *,
    include_other: bool = True,
) -> list[str]:
    options = [c.question for c in candidates[:_MAX_OPTIONS]]
    if include_other and options and _OTHER_OPTION not in options:
        if len(options) >= _MAX_OPTIONS:
            options = options[: _MAX_OPTIONS - 1]
        options.append(_OTHER_OPTION)
    return options


def _pick_by_knowns(
    question: str,
    candidates: list[InterpretationCandidate],
    *,
    rules: list[str],
    golden_questions: list[str],
    conversation_history: list[dict[str, Any]] | None,
) -> InterpretationCandidate | None:
    """If rules, goldens, or history clearly select one candidate, return it.

    A sole candidate is NOT treated as "known" — that is a separate path
    (``single_candidate``) so the execution gate can still run when needed.
    """
    if not candidates:
        return None

    q_tokens = _content_tokens(question)
    # Prefer a candidate whose question is close to a golden.
    for golden in golden_questions or []:
        g_tokens = _content_tokens(golden)
        if not g_tokens:
            continue
        best: InterpretationCandidate | None = None
        best_score = 0
        for cand in candidates:
            c_tokens = _content_tokens(cand.question)
            score = len(g_tokens & c_tokens)
            if score > best_score and score >= 2:
                best_score = score
                best = cand
        if best is not None:
            return best

    # Rule keyword that uniquely overlaps one candidate's question.
    for rule in rules or []:
        r_tokens = _content_tokens(rule)
        if not r_tokens or not (q_tokens & r_tokens):
            continue
        hits = [
            c
            for c in candidates
            if len(_content_tokens(c.question) & r_tokens) >= 2
        ]
        if len(hits) == 1:
            return hits[0]

    # History: if the prior turn's answer/SQL tokens align with one candidate.
    if conversation_history:
        last = conversation_history[-1]
        if isinstance(last, dict):
            hist_text = " ".join(
                str(last.get(k) or "") for k in ("question", "sql", "answer")
            )
            h_tokens = _content_tokens(hist_text)
            if h_tokens:
                scored = [
                    (len(_content_tokens(c.question) & h_tokens), c)
                    for c in candidates
                ]
                scored.sort(key=lambda x: x[0], reverse=True)
                if scored and scored[0][0] >= 2:
                    if len(scored) == 1 or scored[0][0] > scored[1][0]:
                        return scored[0][1]
    return None


def prior_turn_was_clarification(
    conversation_history: list[dict[str, Any]] | None,
) -> bool:
    """Budget heuristic: last turn had an answer but no SQL → clarification."""
    if not conversation_history:
        return False
    last = conversation_history[-1]
    if not isinstance(last, dict):
        return False
    sql = str(last.get("sql") or "").strip()
    answer = str(last.get("answer") or "").strip()
    trust = str(last.get("trust_level") or "").strip().lower()
    if trust == "clarifying":
        return True
    return bool(answer) and not sql


def _candidate_table_set(candidate: InterpretationCandidate) -> frozenset[str]:
    return frozenset(_norm_name(t) for t in candidate.tables if _norm_name(t))


def _candidate_column_set(candidate: InterpretationCandidate) -> frozenset[str]:
    refs: set[str] = set()
    for raw in candidate.columns:
        table, column = _split_table_column(str(raw))
        if table and column:
            refs.add(f"{table}.{column}")
        elif column:
            refs.add(column)
    return frozenset(refs)


def _candidates_materially_different(
    valid: list[InterpretationCandidate],
) -> bool:
    """True when candidates cite different tables or columns.

    Intentionally schema-only — no English measure/filter word lists.
    Implementation-level ambiguity (join type, NULL handling) is decided by
    the execution-evidence gate after SQL candidates are run.
    """
    if len(valid) < 2:
        return False

    for i, left in enumerate(valid):
        left_tables = _candidate_table_set(left)
        left_cols = _candidate_column_set(left)
        for right in valid[i + 1 :]:
            if left_tables != _candidate_table_set(right):
                return True
            if left_cols != _candidate_column_set(right):
                return True
    return False


def parse_interpretation_payload(raw: Any) -> InterpretationProposal:
    """Coerce LLM JSON into a typed proposal. Invalid → unanswerable empty."""
    if not isinstance(raw, dict):
        return InterpretationProposal(
            status="unanswerable",
            assumption="",
            reason="Invalid interpretation payload",
            candidates=(),
        )
    status = str(raw.get("status") or "").strip().lower()
    if status not in {"clear", "assumed", "ambiguous", "unanswerable"}:
        status = "ambiguous"
    assumption = str(raw.get("assumption") or "").strip()
    reason = str(raw.get("reason") or "").strip()
    candidates_raw = raw.get("candidates") or []
    if not isinstance(candidates_raw, list):
        candidates_raw = []
    candidates: list[InterpretationCandidate] = []
    for item in candidates_raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        tables_raw = item.get("tables") or []
        columns_raw = item.get("columns") or []
        if not isinstance(tables_raw, list):
            tables_raw = [tables_raw]
        if not isinstance(columns_raw, list):
            columns_raw = [columns_raw]
        candidates.append(
            InterpretationCandidate(
                label=label or question[:_MAX_LABEL_LEN],
                question=question,
                tables=tuple(str(t) for t in tables_raw if str(t).strip()),
                columns=tuple(str(c) for c in columns_raw if str(c).strip()),
            )
        )
    return InterpretationProposal(
        status=status,
        assumption=assumption,
        reason=reason,
        candidates=tuple(candidates),
    )
