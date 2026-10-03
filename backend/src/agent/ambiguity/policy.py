"""Rule-conflict gate and interpretation ask-vs-proceed policy."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.agent.ambiguity.candidates import (
    _candidates_materially_different,
    _options_from_candidates,
    _pick_by_knowns,
    prior_turn_was_clarification,
    validate_candidates,
)
from src.agent.ambiguity.types import (
    _OTHER_OPTION,
    AmbiguityDecision,
    InterpretationCandidate,
    InterpretationProposal,
    PolicyDecision,
    _content_tokens,
)


def _rule_keyword_overlap(question_tokens: set[str], rule: str) -> set[str]:
    return question_tokens & _content_tokens(rule)


def _looks_like_relationship_rule(text: str) -> bool:
    """Join-path / FK lines from the semantic layer are not metric conflicts."""
    t = (text or "").strip().lower()
    if not t:
        return False
    if t.startswith("relationships"):
        return True
    # e.g. orders.customer_id = customers.id  OR  a.b → c.d [approved]
    if "→" in text or "->" in text:
        return True
    if " = " in t and "." in t and " means " not in t:
        return True
    if "[approved]" in t or "[proposed]" in t:
        return True
    return False


def _rules_conflict(question: str, rules: list[str]) -> tuple[bool, str, list[str]]:
    q_tokens = _content_tokens(question)
    if not q_tokens:
        return False, "", []

    indexed: list[tuple[set[str], set[str], str]] = []
    for rule in rules:
        content = (rule or "").strip()
        if not content or _looks_like_relationship_rule(content):
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

def _assume_top_candidate(
    valid: list[InterpretationCandidate],
    *,
    proposal: InterpretationProposal,
    decision_why: str,
    reason: str,
    needs_execution_gate: bool = False,
    decision_points: tuple[str, ...] = (),
) -> PolicyDecision:
    selected = valid[0]
    return PolicyDecision(
        should_clarify=False,
        status="assumed",
        reason=reason,
        assumption=proposal.assumption
        or f"Assumed: {selected.label or selected.question}",
        options=[c.question for c in valid[1:4]],
        decision_why=decision_why,
        selected=selected,
        needs_execution_gate=needs_execution_gate,
        decision_points=decision_points,
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
    defer_ask_to_execution_gate: bool = False,
    decision_points: Iterable[str] | None = None,
) -> PolicyDecision:
    """Deterministic ask-or-proceed policy. Never invents schema facts.

    Ask only when status is ambiguous (or clear with multiple materially
    different readings), there are ≥2 grounded candidates, knowns do not
    resolve, candidates differ by tables/columns (not phrasing), and the
    clarification budget is not spent. Otherwise proceed as assumed.

    When ``defer_ask_to_execution_gate`` is True, potential asks become
    assumed-with-``needs_execution_gate`` so the execution-evidence node
    can sample SQL and decide from result clusters.
    """
    valid = validate_candidates(
        proposal.candidates,
        tables=tables,
        column_pairs=column_pairs,
        bare_columns=bare_columns,
    )
    budget_spent = prior_turn_was_clarification(conversation_history)
    material = _candidates_materially_different(valid)
    dpoints = tuple(
        str(p).strip() for p in (decision_points or ()) if str(p).strip()
    )

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
            needs_execution_gate=bool(dpoints),
            decision_points=dpoints,
        )

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
            decision_points=dpoints,
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
        # Real knowns resolve the ask; still gate when decision_points exist.
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
            needs_execution_gate=bool(dpoints) if defer_ask_to_execution_gate else False,
            decision_points=dpoints,
        )

    status_allows_ask = proposal.status == "ambiguous" or (
        proposal.status == "clear" and len(valid) > 1 and material
    )
    if (
        status_allows_ask
        and len(valid) >= 2
        and material
        and not budget_spent
    ):
        if defer_ask_to_execution_gate:
            selected = valid[0]
            return PolicyDecision(
                should_clarify=False,
                status="assumed",
                reason=proposal.reason
                or f"{len(valid)} readings deferred to execution-evidence gate",
                assumption=proposal.assumption
                or f"Assumed: {selected.label or selected.question}",
                options=_options_from_candidates(valid, include_other=False)[:3],
                decision_why=(
                    f"defer_execution_gate;candidates={len(valid)};material"
                ),
                selected=selected,
                needs_execution_gate=True,
                decision_points=dpoints,
            )
        return PolicyDecision(
            should_clarify=True,
            status="ambiguous",
            reason=proposal.reason
            or f"{len(valid)} materially different schema-grounded readings",
            assumption="",
            options=_options_from_candidates(valid, include_other=True),
            decision_why=f"ask;candidates={len(valid)};material;budget_ok",
            selected=None,
            decision_points=dpoints,
        )

    # Non-clear outcomes defer to the execution gate when enabled so join-type /
    # aggregation / NULL differences are not bypassed by table/column equality.
    gate_nonclear = defer_ask_to_execution_gate and proposal.status != "clear"

    if len(valid) >= 2:
        if budget_spent and material:
            return _assume_top_candidate(
                valid,
                proposal=proposal,
                decision_why=f"budget_spent;candidates={len(valid)}",
                reason="Clarification budget spent; proceeding with top candidate",
                needs_execution_gate=gate_nonclear or bool(dpoints),
                decision_points=dpoints,
            )
        if not material:
            return _assume_top_candidate(
                valid,
                proposal=proposal,
                decision_why=f"assumed_immaterial;candidates={len(valid)}",
                reason=proposal.reason
                or "Candidates differ only by phrasing/join path; proceeding",
                needs_execution_gate=defer_ask_to_execution_gate or bool(dpoints),
                decision_points=dpoints,
            )
        return _assume_top_candidate(
            valid,
            proposal=proposal,
            decision_why=(
                f"assumed;status={proposal.status};candidates={len(valid)}"
            ),
            reason=proposal.reason
            or "Proceeding with top grounded candidate",
            needs_execution_gate=gate_nonclear or bool(dpoints),
            decision_points=dpoints,
        )

    if len(valid) == 1:
        selected = valid[0]
        # Truthful reason: single grounded candidate, not "resolved_known".
        # (clear + 1 already returned above; this path is non-clear.)
        return PolicyDecision(
            should_clarify=False,
            status="assumed",
            reason=proposal.reason or "Single grounded reading",
            assumption=proposal.assumption
            or f"Assumed: {selected.label or selected.question}",
            options=[],
            decision_why="single_candidate;candidates=1",
            selected=selected,
            needs_execution_gate=bool(defer_ask_to_execution_gate or dpoints),
            decision_points=dpoints,
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
        needs_execution_gate=False,
        decision_points=dpoints,
    )
