"""LLM usage and timing tracker for eval pilots. No effect unless activated."""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import ChatGeneration, LLMResult

# Active tracker for the current async task / thread.
_ACTIVE_TRACKER: ContextVar[Optional["UsageTracker"]] = ContextVar(
    "astrasql_usage_tracker", default=None
)
_ACTIVE_STAGE: ContextVar[str] = ContextVar("astrasql_usage_stage", default="")
_ACTIVE_CASE: ContextVar[str] = ContextVar("astrasql_usage_case", default="")
_ACTIVE_LABEL: ContextVar[str] = ContextVar("astrasql_usage_label", default="")


@dataclass(frozen=True)
class ModelRates:
    input_per_m: float
    output_per_m: float
    cached_input_per_m: float = 0.0


@dataclass
class RateCard:
    """Dollar rates per 1M tokens. Reasoning tokens bill as output."""

    models: dict[str, ModelRates] = field(default_factory=dict)
    embedding_per_m: float = 0.02

    @classmethod
    def default(cls) -> "RateCard":
        return cls(
            models={
                "gpt-5.6-luna": ModelRates(0.20, 1.20, 0.02),
                "gpt-4o": ModelRates(2.50, 10.00, 1.25),
                "gpt-4o-mini": ModelRates(0.15, 0.60, 0.075),
            },
            embedding_per_m=0.02,
        )

    def rates_for(self, model: str) -> ModelRates:
        key = (model or "").strip()
        if key in self.models:
            return self.models[key]
        # Prefix match (e.g. gpt-5.6-luna-2026-...)
        for name, rates in self.models.items():
            if key.startswith(name):
                return rates
        # Unknown model: use luna rates and let the report show the model name.
        return self.models.get("gpt-5.6-luna", ModelRates(0.20, 1.20, 0.02))

    def chat_cost(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
    ) -> float:
        rates = self.rates_for(model)
        billed_input = max(0, int(input_tokens) - int(cached_input_tokens))
        cached = max(0, int(cached_input_tokens))
        return (
            billed_input * rates.input_per_m / 1_000_000
            + cached * rates.cached_input_per_m / 1_000_000
            + int(output_tokens) * rates.output_per_m / 1_000_000
        )

    def embedding_cost(self, tokens: int) -> float:
        return int(tokens) * self.embedding_per_m / 1_000_000


@dataclass
class CallRecord:
    kind: str  # chat | embedding
    model: str
    stage: str
    case_id: str
    label: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_input_tokens: int
    latency_ms: int
    cost_usd: float
    estimated: bool = False


@dataclass
class UsageTracker:
    rate_card: RateCard = field(default_factory=RateCard.default)
    records: list[CallRecord] = field(default_factory=list)
    _starts: dict[str, float] = field(default_factory=dict)

    def record_chat(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
        cached_input_tokens: int = 0,
        latency_ms: int = 0,
        estimated: bool = False,
        stage: str | None = None,
        case_id: str | None = None,
        label: str | None = None,
    ) -> CallRecord:
        # Reasoning tokens are billed as output; if the API reports them
        # separately and also includes them in output_tokens, do not double-count.
        billed_output = int(output_tokens)
        cost = self.rate_card.chat_cost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=billed_output,
            cached_input_tokens=cached_input_tokens,
        )
        rec = CallRecord(
            kind="chat",
            model=model,
            stage=stage if stage is not None else _ACTIVE_STAGE.get(),
            case_id=case_id if case_id is not None else _ACTIVE_CASE.get(),
            label=label if label is not None else _ACTIVE_LABEL.get(),
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            reasoning_tokens=int(reasoning_tokens),
            cached_input_tokens=int(cached_input_tokens),
            latency_ms=int(latency_ms),
            cost_usd=round(cost, 8),
            estimated=estimated,
        )
        self.records.append(rec)
        return rec

    def record_embedding(
        self,
        *,
        model: str,
        tokens: int,
        latency_ms: int = 0,
        estimated: bool = False,
        stage: str | None = None,
        case_id: str | None = None,
        label: str | None = None,
    ) -> CallRecord:
        cost = self.rate_card.embedding_cost(tokens)
        rec = CallRecord(
            kind="embedding",
            model=model,
            stage=stage if stage is not None else _ACTIVE_STAGE.get(),
            case_id=case_id if case_id is not None else _ACTIVE_CASE.get(),
            label=label if label is not None else _ACTIVE_LABEL.get(),
            input_tokens=int(tokens),
            output_tokens=0,
            reasoning_tokens=0,
            cached_input_tokens=0,
            latency_ms=int(latency_ms),
            cost_usd=round(cost, 8),
            estimated=estimated,
        )
        self.records.append(rec)
        return rec

    def total_cost(self) -> float:
        return round(sum(r.cost_usd for r in self.records), 8)

    def summary_by_stage(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for rec in self.records:
            key = rec.stage or "(unset)"
            bucket = out.setdefault(
                key,
                {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                    "cached_input_tokens": 0,
                    "latency_ms": 0,
                    "cost_usd": 0.0,
                    "estimated_calls": 0,
                },
            )
            bucket["calls"] += 1
            bucket["input_tokens"] += rec.input_tokens
            bucket["output_tokens"] += rec.output_tokens
            bucket["reasoning_tokens"] += rec.reasoning_tokens
            bucket["cached_input_tokens"] += rec.cached_input_tokens
            bucket["latency_ms"] += rec.latency_ms
            bucket["cost_usd"] = round(bucket["cost_usd"] + rec.cost_usd, 8)
            if rec.estimated:
                bucket["estimated_calls"] += 1
        return out

    def summary_for_case(self, case_id: str) -> dict[str, Any]:
        rows = [r for r in self.records if r.case_id == case_id]
        return {
            "calls": len(rows),
            "input_tokens": sum(r.input_tokens for r in rows),
            "output_tokens": sum(r.output_tokens for r in rows),
            "reasoning_tokens": sum(r.reasoning_tokens for r in rows),
            "cached_input_tokens": sum(r.cached_input_tokens for r in rows),
            "latency_ms": sum(r.latency_ms for r in rows),
            "cost_usd": round(sum(r.cost_usd for r in rows), 8),
            "estimated_calls": sum(1 for r in rows if r.estimated),
            "by_stage": _stage_summary(rows),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cost_usd": self.total_cost(),
            "total_calls": len(self.records),
            "estimated_calls": sum(1 for r in self.records if r.estimated),
            "by_stage": self.summary_by_stage(),
            "records": [
                {
                    "kind": r.kind,
                    "model": r.model,
                    "stage": r.stage,
                    "case_id": r.case_id,
                    "label": r.label,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "reasoning_tokens": r.reasoning_tokens,
                    "cached_input_tokens": r.cached_input_tokens,
                    "latency_ms": r.latency_ms,
                    "cost_usd": r.cost_usd,
                    "estimated": r.estimated,
                }
                for r in self.records
            ],
        }


def _stage_summary(rows: list[CallRecord]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rec in rows:
        key = rec.stage or "(unset)"
        bucket = out.setdefault(
            key,
            {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "latency_ms": 0,
                "cost_usd": 0.0,
            },
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += rec.input_tokens
        bucket["output_tokens"] += rec.output_tokens
        bucket["reasoning_tokens"] += rec.reasoning_tokens
        bucket["latency_ms"] += rec.latency_ms
        bucket["cost_usd"] = round(bucket["cost_usd"] + rec.cost_usd, 8)
    return out


def get_active_tracker() -> Optional[UsageTracker]:
    return _ACTIVE_TRACKER.get()


@contextmanager
def track_usage(tracker: UsageTracker) -> Iterator[UsageTracker]:
    token = _ACTIVE_TRACKER.set(tracker)
    try:
        yield tracker
    finally:
        _ACTIVE_TRACKER.reset(token)


@contextmanager
def usage_stage(stage: str, *, label: str = "") -> Iterator[None]:
    stage_token = _ACTIVE_STAGE.set(stage)
    label_token = _ACTIVE_LABEL.set(label)
    try:
        yield
    finally:
        _ACTIVE_STAGE.reset(stage_token)
        _ACTIVE_LABEL.reset(label_token)


@contextmanager
def usage_case(case_id: str) -> Iterator[None]:
    token = _ACTIVE_CASE.set(case_id)
    try:
        yield
    finally:
        _ACTIVE_CASE.reset(token)


def extrapolate(
    *,
    avg_cost_usd: float,
    avg_latency_ms: float,
    n_questions: int,
    setup_cost_usd: float = 0.0,
    setup_latency_ms: int = 0,
) -> dict[str, Any]:
    return {
        "n_questions": n_questions,
        "setup_cost_usd": round(setup_cost_usd, 6),
        "questions_cost_usd": round(avg_cost_usd * n_questions, 6),
        "total_cost_usd": round(setup_cost_usd + avg_cost_usd * n_questions, 6),
        "avg_cost_per_question_usd": round(avg_cost_usd, 6),
        "avg_latency_ms": round(avg_latency_ms, 1),
        "estimated_total_latency_ms": round(
            setup_latency_ms + avg_latency_ms * n_questions, 1
        ),
    }


def _extract_usage(response: Any) -> tuple[int, int, int, int, bool]:
    """Return (input, output, reasoning, cached_input, estimated)."""
    usage = None
    if isinstance(response, dict):
        usage = response.get("token_usage") or response.get("usage")
    else:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            resp_meta = getattr(response, "response_metadata", None) or {}
            if isinstance(resp_meta, dict):
                usage = resp_meta.get("token_usage") or resp_meta.get("usage")

    if not usage:
        return 0, 0, 0, 0, True

    if isinstance(usage, dict):
        inp = int(
            usage.get("input_tokens")
            or usage.get("prompt_tokens")
            or usage.get("prompt_token_count")
            or 0
        )
        out = int(
            usage.get("output_tokens")
            or usage.get("completion_tokens")
            or usage.get("completion_token_count")
            or 0
        )
        reasoning = 0
        details = usage.get("output_token_details") or usage.get(
            "completion_tokens_details"
        )
        if isinstance(details, dict):
            reasoning = int(details.get("reasoning") or details.get("reasoning_tokens") or 0)
        elif usage.get("reasoning_tokens") is not None:
            reasoning = int(usage.get("reasoning_tokens") or 0)
        cached = 0
        in_details = usage.get("input_token_details") or usage.get(
            "prompt_tokens_details"
        )
        if isinstance(in_details, dict):
            cached = int(in_details.get("cache_read") or in_details.get("cached_tokens") or 0)
        elif usage.get("cached_tokens") is not None:
            cached = int(usage.get("cached_tokens") or 0)
        estimated = inp == 0 and out == 0
        return inp, out, reasoning, cached, estimated

    # pydantic / object style
    inp = int(getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0) or 0)
    out = int(
        getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0) or 0
    )
    reasoning = 0
    details = getattr(usage, "output_token_details", None) or getattr(
        usage, "completion_tokens_details", None
    )
    if details is not None:
        reasoning = int(
            getattr(details, "reasoning", 0)
            or getattr(details, "reasoning_tokens", 0)
            or 0
        )
    cached = 0
    in_details = getattr(usage, "input_token_details", None) or getattr(
        usage, "prompt_tokens_details", None
    )
    if in_details is not None:
        cached = int(
            getattr(in_details, "cache_read", 0)
            or getattr(in_details, "cached_tokens", 0)
            or 0
        )
    estimated = inp == 0 and out == 0
    return inp, out, reasoning, cached, estimated


class UsageCallbackHandler(BaseCallbackHandler):
    """Records chat LLM usage into the active UsageTracker."""

    raise_error: bool = False

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[Any],
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        self._mark_start(str(run_id))

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        self._mark_start(str(run_id))

    def on_llm_end(self, response: LLMResult, *, run_id: Any, **kwargs: Any) -> None:
        tracker = get_active_tracker()
        if tracker is None:
            return
        started = tracker._starts.pop(str(run_id), None)
        latency_ms = int((time.perf_counter() - started) * 1000) if started else 0

        model = ""
        llm_output = response.llm_output or {}
        if isinstance(llm_output, dict):
            model = str(llm_output.get("model_name") or llm_output.get("model") or "")

        # Prefer per-generation message metadata (usage_metadata on AIMessage).
        inp = out = reasoning = cached = 0
        estimated = True
        if response.generations:
            for gen_list in response.generations:
                for gen in gen_list:
                    msg = getattr(gen, "message", None) if isinstance(gen, ChatGeneration) else None
                    target = msg if msg is not None else gen
                    i, o, r, c, est = _extract_usage(target)
                    if not est:
                        estimated = False
                    inp += i
                    out += o
                    reasoning += r
                    cached += c
                    if not model and msg is not None:
                        meta = getattr(msg, "response_metadata", None) or {}
                        if isinstance(meta, dict):
                            model = str(meta.get("model_name") or meta.get("model") or "")

        if estimated and isinstance(llm_output, dict):
            i, o, r, c, est = _extract_usage(llm_output)
            if not est:
                estimated = False
                inp, out, reasoning, cached = i, o, r, c

        tracker.record_chat(
            model=model or "unknown",
            input_tokens=inp,
            output_tokens=out,
            reasoning_tokens=reasoning,
            cached_input_tokens=cached,
            latency_ms=latency_ms,
            estimated=estimated,
        )

    def on_llm_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        tracker = get_active_tracker()
        if tracker is not None:
            tracker._starts.pop(str(run_id), None)

    def _mark_start(self, run_id: str) -> None:
        tracker = get_active_tracker()
        if tracker is not None:
            tracker._starts[run_id] = time.perf_counter()


def make_usage_callbacks() -> list[BaseCallbackHandler]:
    """Return callbacks to attach when a tracker is active; else empty."""
    if get_active_tracker() is None:
        return []
    return [UsageCallbackHandler()]
