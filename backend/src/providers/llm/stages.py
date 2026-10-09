"""Per-stage LLM budgets (max_tokens + reasoning effort)."""

from __future__ import annotations

from typing import Any

from src.config.settings import Settings, get_settings

# Stages that should stay cheap (routing / narrative / retrieval helpers).
_MINIMAL_STAGES = frozenset(
    {
        "intent_classifier",
        "intent",
        "expansion",
        "schema_expand",
        "formatter",
        "response_formatter",
        "direct_response",
        "schema_fine",
        "fine_select",
    }
)

_ESCALATION_STAGES = frozenset(
    {
        "repair",
        "repair_agent",
        "escalation",
    }
)


def resolve_reasoning_effort(
    stage: str | None = None,
    *,
    settings: Settings | None = None,
    escalate: bool = False,
) -> str:
    """Return reasoning effort for a named stage."""
    s = settings or get_settings()
    stage_key = (stage or "").strip().lower()

    if escalate or stage_key in _ESCALATION_STAGES:
        override = (s.repair_reasoning_effort or "").strip().lower()
        return override or "medium"

    def _normalize(value: str) -> str:
        v = (value or "").strip().lower()
        if v in {"minimal", "off"}:
            return "none"
        return v

    if stage_key in {"intent_classifier", "intent"}:
        return _normalize(s.intent_reasoning_effort or "none") or "none"
    if stage_key in {"formatter", "response_formatter"}:
        return _normalize(s.formatter_reasoning_effort or "none") or "none"
    if stage_key in {"expansion", "schema_expand"}:
        return _normalize(s.expansion_reasoning_effort or "none") or "none"
    if stage_key in {
        "query_generator",
        "generator",
        "ambiguity_gate",
        "candidates",
    }:
        override = _normalize(s.generator_reasoning_effort or "")
        return override or _normalize(s.llm_reasoning_effort or "low") or "low"

    if stage_key in _MINIMAL_STAGES:
        return "none"

    return _normalize(s.llm_reasoning_effort or "low") or "low"


def resolve_max_tokens(
    stage: str | None = None,
    *,
    settings: Settings | None = None,
) -> int:
    """Return max_tokens cap for a named stage."""
    s = settings or get_settings()
    stage_key = (stage or "").strip().lower()
    default = int(s.llm_max_tokens or 4096)

    mapping = {
        "intent_classifier": s.intent_max_tokens,
        "intent": s.intent_max_tokens,
        "formatter": s.formatter_max_tokens,
        "response_formatter": s.formatter_max_tokens,
        "expansion": s.expansion_max_tokens,
        "schema_expand": s.expansion_max_tokens,
        "query_generator": s.generator_max_tokens,
        "generator": s.generator_max_tokens,
        "ambiguity_gate": s.generator_max_tokens,
        "candidates": s.generator_max_tokens,
        "query_validator": s.validator_max_tokens,
        "validator": s.validator_max_tokens,
        "direct_response": s.direct_max_tokens,
        "interpretation_resolver": min(default, 2048),
        "repair": s.generator_max_tokens,
        "repair_agent": s.generator_max_tokens,
        "schema_fine": s.expansion_max_tokens or 512,
        "fine_select": s.expansion_max_tokens or 512,
    }
    value = mapping.get(stage_key)
    if value is None or int(value) <= 0:
        return default
    return int(value)


def stage_chat_kwargs(
    stage: str | None = None,
    *,
    settings: Settings | None = None,
    escalate: bool = False,
    model: str | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Kwargs for ``get_chat_model`` for a named stage."""
    s = settings or get_settings()
    return {
        "temperature": temperature,
        "max_tokens": resolve_max_tokens(stage, settings=s),
        "model": model,
        "reasoning_effort": resolve_reasoning_effort(
            stage, settings=s, escalate=escalate
        ),
    }
