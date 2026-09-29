"""Conservative, deterministic ambiguity gate. No LLM, no IO.

Pre-SQL: only conflicting *project* rules. Identity slots are checked
after SQL is written — see ``src.agent.provenance``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Letters/digits in any script. No English stopword list.
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


@dataclass(frozen=True)
class AmbiguityDecision:
    should_clarify: bool
    reason: str
    options: list[str]


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
