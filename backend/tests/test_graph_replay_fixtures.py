"""Replay fixtures for graph routing after generate / gate (no live LLM)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.graph import route_after_gate, route_after_generate

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "graph_replay.json"


@pytest.fixture(scope="module")
def replay_cases() -> list[dict]:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return list(data["cases"])


def _state_from_fixture(case: dict) -> dict:
    return {
        "ambiguity": dict(case.get("ambiguity") or {}),
        "sql": case.get("sql"),
        "question": case.get("question") or "",
    }


def test_replay_route_after_generate_statuses(replay_cases, monkeypatch):
    from src.config.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("EXECUTION_EVIDENCE_GATE", "true")
    get_settings.cache_clear()

    by_status = {c["status"]: c for c in replay_cases if c.get("route") == "after_generate"}
    assert "clear" in by_status
    assert "assumed" in by_status
    assert "ambiguous" in by_status

    clear = _state_from_fixture(by_status["clear"])
    assert route_after_generate(clear) == "validate"

    assumed = _state_from_fixture(by_status["assumed"])
    # Assumed with decision_points / needs_execution_gate → gate
    assert route_after_generate(assumed) == "gate"

    amb = _state_from_fixture(by_status["ambiguous"])
    assert route_after_generate(amb) == "clarify"

    get_settings.cache_clear()


def test_replay_route_after_gate(replay_cases):
    cases = [c for c in replay_cases if c.get("route") == "after_gate"]
    assert cases
    for case in cases:
        state = _state_from_fixture(case)
        assert route_after_gate(state) == case["expected"]


def test_stub_generator_status_drives_routing(monkeypatch):
    """Monkeypatch-style: recorded generator ambiguity status → route."""
    from src.config.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("EXECUTION_EVIDENCE_GATE", "true")
    get_settings.cache_clear()

    recorded = {
        "clear": {"status": "clear", "should_clarify": False},
        "assumed": {
            "status": "assumed",
            "should_clarify": False,
            "needs_execution_gate": True,
            "decision_points": [{"kind": "join"}],
        },
        "ambiguous": {"status": "ambiguous", "should_clarify": True},
    }

    def fake_generator_output(status_key: str) -> dict:
        return {"ambiguity": recorded[status_key], "sql": "SELECT 1"}

    assert route_after_generate(fake_generator_output("clear")) == "validate"
    assert route_after_generate(fake_generator_output("assumed")) == "gate"
    assert route_after_generate(fake_generator_output("ambiguous")) == "clarify"

    # Gate outcomes
    assert (
        route_after_gate(
            {"ambiguity": {"should_clarify": False, "status": "clear"}}
        )
        == "validate"
    )
    assert (
        route_after_gate(
            {"ambiguity": {"should_clarify": True, "status": "ambiguous"}}
        )
        == "clarify"
    )
    get_settings.cache_clear()


def test_llm_cache_record_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRASQL_LLM_CACHE", "1")
    monkeypatch.setenv("ASTRASQL_LLM_CACHE_DIR", str(tmp_path))

    from src.eval import llm_cache

    messages = [{"role": "user", "content": "hello"}]
    assert llm_cache.read_cache("gpt-test", messages) is None
    llm_cache.write_cache("gpt-test", messages, "world")
    assert llm_cache.read_cache("gpt-test", messages) == "world"

    # Disabled → no read
    monkeypatch.setenv("ASTRASQL_LLM_CACHE", "0")
    assert llm_cache.read_cache("gpt-test", messages) is None
