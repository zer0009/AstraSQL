from src.observability.usage import (
    RateCard,
    UsageTracker,
    _extract_usage,
    extrapolate,
)


def test_rate_card_chat_cost():
    card = RateCard.default()
    # 1M input @ 0.20 + 1M output @ 1.20 = 1.40
    assert abs(card.chat_cost(model="gpt-5.6-luna", input_tokens=1_000_000, output_tokens=1_000_000) - 1.40) < 1e-9
    # Cached input uses cached rate
    cost = card.chat_cost(
        model="gpt-5.6-luna",
        input_tokens=1_000_000,
        output_tokens=0,
        cached_input_tokens=500_000,
    )
    # 500k billed input * 0.20 + 500k cached * 0.02 = 0.10 + 0.01 = 0.11
    assert abs(cost - 0.11) < 1e-9


def test_rate_card_prefix_match():
    card = RateCard.default()
    rates = card.rates_for("gpt-5.6-luna-2026-09-01")
    assert rates.input_per_m == 0.20


def test_tracker_records_and_summarizes():
    tracker = UsageTracker(rate_card=RateCard.default())
    tracker.record_chat(
        model="gpt-5.6-luna",
        input_tokens=1000,
        output_tokens=100,
        reasoning_tokens=50,
        latency_ms=120,
        stage="intent_classifier",
        case_id="q1",
    )
    tracker.record_chat(
        model="gpt-5.6-luna",
        input_tokens=2000,
        output_tokens=200,
        reasoning_tokens=0,
        latency_ms=300,
        stage="query_generator",
        case_id="q1",
        estimated=True,
    )
    summary = tracker.summary_for_case("q1")
    assert summary["calls"] == 2
    assert summary["input_tokens"] == 3000
    assert summary["output_tokens"] == 300
    assert summary["reasoning_tokens"] == 50
    assert summary["estimated_calls"] == 1
    assert summary["cost_usd"] > 0
    assert "intent_classifier" in summary["by_stage"]
    assert tracker.total_cost() == summary["cost_usd"]


def test_extract_usage_from_dict():
    inp, out, reasoning, cached, estimated = _extract_usage(
        {
            "token_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "completion_tokens_details": {"reasoning_tokens": 2},
                "prompt_tokens_details": {"cached_tokens": 3},
            }
        }
    )
    assert (inp, out, reasoning, cached, estimated) == (10, 5, 2, 3, False)


def test_extract_usage_missing_is_estimated():
    inp, out, reasoning, cached, estimated = _extract_usage({})
    assert estimated is True
    assert inp == 0 and out == 0


def test_extrapolate():
    result = extrapolate(
        avg_cost_usd=0.01,
        avg_latency_ms=2000,
        n_questions=1034,
        setup_cost_usd=0.05,
        setup_latency_ms=5000,
    )
    assert result["n_questions"] == 1034
    assert abs(result["questions_cost_usd"] - 10.34) < 1e-9
    assert abs(result["total_cost_usd"] - 10.39) < 1e-9
