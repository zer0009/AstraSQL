"""Conservative, deterministic ambiguity gate. No LLM, no IO.

Pre-SQL: only conflicting *project* rules. Identity slots are checked
after SQL is written — see ``src.agent.provenance``.

Schema-grounded interpretation policy (ask vs proceed) lives here too:
the LLM may propose candidates; this module decides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# Letters/digits in any script. No English stopword list.
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)

_MAX_OPTIONS = 4
_MAX_LABEL_LEN = 80
_OTHER_OPTION = "Other — I'll rephrase the question"


@dataclass(frozen=True)
class AmbiguityDecision:
    should_clarify: bool
    reason: str
    options: list[str]


@dataclass(frozen=True)
class InterpretationCandidate:
    label: str
    question: str
    tables: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class InterpretationProposal:
    status: str  # clear | assumed | ambiguous | unanswerable
    assumption: str
    reason: str
    candidates: tuple[InterpretationCandidate, ...] = ()


@dataclass(frozen=True)
class PolicyDecision:
    should_clarify: bool
    status: str  # clear | assumed | ambiguous | unanswerable | failed_open
    reason: str
    assumption: str
    options: list[str] = field(default_factory=list)
    decision_why: str = ""
    selected: Optional[InterpretationCandidate] = None


def _tokens(text: str) -> list[str]:
    # Split snake_case identifiers so schema names match spoken words.
    parts: list[str] = []
    for match in _TOKEN_RE.finditer(text or ""):
        parts.extend(p for p in match.group(0).lower().split("_") if p)
    return parts


def _content_tokens(text: str) -> set[str]:
    return {t for t in _tokens(text) if len(t) > 1}


def _rule_keyword_overlap(question_tokens: set[str], rule: str) -> set[str]:
    return question_tokens & _content_tokens(rule)


def _rules_conflict(question: str, rules: list[str]) -> tuple[bool, str, list[str]]:
    q_tokens = _content_tokens(question)
    if not q_tokens:
        return False, "", []

    indexed: list[tuple[set[str], set[str], str]] = []
    for rule in rules:
        content = (rule or "").strip()
        if not content:
            continue
        overlap = _rule_keyword_overlap(q_tokens, content)
        if not overlap:
            continue
        indexed.append((overlap, _content_tokens(content), content))

    for i, (overlap_a, tokens_a, text_a) in enumerate(indexed):
        for overlap_b, tokens_b, text_b in indexed[i + 1 :]:
            shared = overlap_a & overlap_b
            if not shared:
                continue
            rest_a = tokens_a - overlap_a
            rest_b = tokens_b - overlap_b
            if rest_a == rest_b:
                continue
            distinct_a = tokens_a - tokens_b
            distinct_b = tokens_b - tokens_a
            picks_a = bool(q_tokens & distinct_a)
            picks_b = bool(q_tokens & distinct_b)
            if picks_a != picks_b:
                continue
            keyword = next(iter(shared))
            return (
                True,
                f"Conflicting rules for '{keyword}'",
                _options_from_rules(keyword, text_a, text_b),
            )
    return False, "", []


def _options_from_rules(keyword: str, rule_a: str, rule_b: str) -> list[str]:
    options: list[str] = []
    for rule in (rule_a, rule_b):
        snippet = rule.strip()
        if len(snippet) > 80:
            snippet = snippet[:77] + "..."
        options.append(f"Use the definition: {snippet}")
    if keyword:
        options.append(f"What should '{keyword}' mean for this question?")
    return options[:4]


def _has_close_golden(question: str, golden_questions: list[str]) -> bool:
    q_tokens = _content_tokens(question)
    if not q_tokens:
        return False
    for golden in golden_questions:
        g_tokens = _content_tokens(golden)
        if not g_tokens:
            continue
        overlap = q_tokens & g_tokens
        if len(overlap) >= 2 or (len(q_tokens) <= 2 and overlap):
            return True
        if q_tokens <= g_tokens or g_tokens <= q_tokens:
            return True
    return False


def decide_ambiguity(
    question: str,
    *,
    rules: list[str],
    golden_questions: list[str],
) -> AmbiguityDecision:
    """Return whether we must ask before generating SQL.

    Only rule conflicts. Missing identity values are detected after SQL
    exists, from the schema graph — not from the user's language.
    """
    conflict, reason, options = _rules_conflict(question, rules)
    if conflict:
        return AmbiguityDecision(True, reason, options)

    if _has_close_golden(question, golden_questions):
        return AmbiguityDecision(False, "Close golden question exists", [])

    return AmbiguityDecision(False, "No conflicting project rules", [])


def _norm_name(name: str) -> str:
    return (name or "").strip().strip('"').lower()


def _split_table_column(ref: str) -> tuple[str, str]:
    text = (ref or "").strip()
    if "." in text:
        table, _, column = text.partition(".")
        return _norm_name(table), _norm_name(column)
    return "", _norm_name(text)


def build_schema_index(
    selected_tables: Iterable[str],
    selected_columns: Iterable[dict[str, Any]] | None = None,
    *,
    extra_columns_by_table: dict[str, Iterable[str]] | None = None,
) -> tuple[set[str], set[tuple[str, str]], set[str]]:
    """Return (tables, (table, column) pairs, bare column names)."""
    tables = {_norm_name(t) for t in selected_tables if _norm_name(t)}
    pairs: set[tuple[str, str]] = set()
    bare: set[str] = set()
    for item in selected_columns or []:
        if not isinstance(item, dict):
            continue
        table = _norm_name(str(item.get("table") or ""))
        column = _norm_name(str(item.get("column") or item.get("name") or ""))
        if column:
            bare.add(column)
        if table and column:
            pairs.add((table, column))
            tables.add(table)
    for table, cols in (extra_columns_by_table or {}).items():
        t = _norm_name(table)
        if not t:
            continue
        tables.add(t)
        for col in cols or []:
            c = _norm_name(str(col))
            if c:
                pairs.add((t, c))
                bare.add(c)
    return tables, pairs, bare


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
) -> Optional[InterpretationCandidate]:
    """If rules, goldens, or history clearly select one candidate, return it."""
    if len(candidates) == 1:
        return candidates[0]

    q_tokens = _content_tokens(question)
    # Prefer a candidate whose question is close to a golden.
    for golden in golden_questions or []:
        g_tokens = _content_tokens(golden)
        if not g_tokens:
            continue
        best: Optional[InterpretationCandidate] = None
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


def apply_interpretation_policy(
    proposal: InterpretationProposal,
    *,
    question: str,
    tables: set[str],
    column_pairs: set[tuple[str, str]],
    bare_columns: set[str],
    rules: list[str],
    golden_questions: list[str],
    conversation_history: list[dict[str, Any]] | None = None,
) -> PolicyDecision:
    """Deterministic ask-or-proceed policy. Never invents schema facts."""
    valid = validate_candidates(
        proposal.candidates,
        tables=tables,
        column_pairs=column_pairs,
        bare_columns=bare_columns,
    )
    budget_spent = prior_turn_was_clarification(conversation_history)

    if proposal.status == "clear" and len(valid) == 1:
        selected = valid[0]
        return PolicyDecision(
            should_clarify=False,
            status="clear",
            reason=proposal.reason or "Question is clear",
            assumption=proposal.assumption,
            options=[],
            decision_why=f"clear;candidates={len(valid)}",
            selected=selected,
        )

    if proposal.status == "clear" and len(valid) > 1:
        # Model claimed clear but listed multiple grounded readings — ask.
        pass

    if proposal.status == "unanswerable" and not valid:
        digest_hint = ", ".join(sorted(tables)[:8]) if tables else "(none)"
        return PolicyDecision(
            should_clarify=True,
            status="unanswerable",
            reason=(
                proposal.reason
                or f"Nothing in the retrieved schema supports this. Closest tables: {digest_hint}"
            ),
            assumption="",
            options=[_OTHER_OPTION],
            decision_why="unanswerable;valid=0",
            selected=None,
        )

    known = _pick_by_knowns(
        question,
        valid,
        rules=rules,
        golden_questions=golden_questions,
        conversation_history=conversation_history,
    )
    if known is not None:
        assumption = (
            proposal.assumption
            or f"Using: {known.label or known.question}"
        )
        return PolicyDecision(
            should_clarify=False,
            status="assumed",
            reason=proposal.reason or "Resolved from rules, golden, or history",
            assumption=assumption,
            options=[
                c.question
                for c in valid
                if c.question != known.question
            ][:3],
            decision_why=f"resolved_known;candidates={len(valid)}",
            selected=known,
        )

    if len(valid) >= 2 and not budget_spent:
        return PolicyDecision(
            should_clarify=True,
            status="ambiguous",
            reason=proposal.reason
            or f"{len(valid)} materially different schema-grounded readings",
            assumption="",
            options=_options_from_candidates(valid, include_other=True),
            decision_why=f"ask;candidates={len(valid)};budget_ok",
            selected=None,
        )

    if len(valid) >= 2 and budget_spent:
        selected = valid[0]
        return PolicyDecision(
            should_clarify=False,
            status="assumed",
            reason="Clarification budget spent; proceeding with top candidate",
            assumption=proposal.assumption
            or f"Assumed: {selected.label or selected.question}",
            options=[c.question for c in valid[1:4]],
            decision_why=f"budget_spent;candidates={len(valid)}",
            selected=selected,
        )

    if len(valid) == 1:
        selected = valid[0]
        return PolicyDecision(
            should_clarify=False,
            status="assumed",
            reason=proposal.reason or "Single grounded reading",
            assumption=proposal.assumption
            or f"Assumed: {selected.label or selected.question}",
            options=[],
            decision_why="assumed;candidates=1",
            selected=selected,
        )

    # No valid candidates — fail open (proceed without asking).
    return PolicyDecision(
        should_clarify=False,
        status="failed_open",
        reason=proposal.reason or "No grounded candidates; proceeding to SQL",
        assumption=proposal.assumption,
        options=[],
        decision_why="failed_open;valid=0",
        selected=None,
    )


def build_schema_digest(
    selected_tables: Iterable[str],
    selected_columns: Iterable[dict[str, Any]] | None = None,
    *,
    table_descriptions: dict[str, str] | None = None,
    column_descriptions: dict[str, dict[str, str]] | None = None,
    max_tables: int = 30,
    max_columns_per_table: int = 40,
) -> str:
    """Compact digest for prompts. No sample rows."""
    cols_by_table: dict[str, list[str]] = {}
    for item in selected_columns or []:
        if not isinstance(item, dict):
            continue
        table = str(item.get("table") or "").strip()
        column = str(item.get("column") or item.get("name") or "").strip()
        if table and column:
            cols_by_table.setdefault(table, [])
            if column not in cols_by_table[table]:
                cols_by_table[table].append(column)

    lines: list[str] = []
    tables = list(selected_tables)[:max_tables]
    for table in tables:
        desc = ""
        if table_descriptions and table in table_descriptions:
            desc = (table_descriptions.get(table) or "").strip()
        header = f"{table}" + (f" — {desc}" if desc else "")
        lines.append(header)
        cols = cols_by_table.get(table) or []
        col_descs = (column_descriptions or {}).get(table) or {}
        for col in cols[:max_columns_per_table]:
            cdesc = (col_descs.get(col) or "").strip()
            if cdesc:
                lines.append(f"  - {col}: {cdesc}")
            else:
                lines.append(f"  - {col}")
        if not cols:
            lines.append("  - (columns not fine-selected)")
    return "\n".join(lines) if lines else "(none)"
