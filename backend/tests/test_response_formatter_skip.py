import importlib

import pytest

from src.config.settings import get_settings

# Import module object (not the function) so we can patch get_llm_provider.
rf_mod = importlib.import_module("src.agent.nodes.response_formatter")


def test_deterministic_answer_preview():
    answer, key = rf_mod._deterministic_answer(
        {
            "row_count": 3,
            "columns": ["id", "name", "city"],
            "rows": [{"id": 1, "name": "a", "city": "x"}],
        },
        None,
    )
    assert "Returned 3 rows" in answer
    assert "id" in answer
    assert key == "3 row(s)"


@pytest.mark.asyncio
async def test_formatter_skips_llm_when_format_response_off(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("FORMAT_RESPONSE", "false")
    get_settings.cache_clear()

    called = {"llm": False}

    class _Boom:
        def get_chat_model(self, **kwargs):
            called["llm"] = True
            raise AssertionError("LLM should not be called")

    monkeypatch.setattr(rf_mod, "get_llm_provider", lambda: _Boom())

    state = {
        "question": "how many?",
        "sql": "SELECT 1",
        "results": {
            "row_count": 2,
            "columns": ["n"],
            "rows": [{"n": 1}, {"n": 2}],
        },
        "retries": 0,
        "intent": "SQL_QUERY",
        "used_golden": False,
        "context": {"golden_sqls": []},
        "steps": [],
    }
    out = await rf_mod.response_formatter(state, config={})
    assert called["llm"] is False
    assert "Returned 2 rows" in out["answer"]
    assert out["confidence"] in {"HIGH", "MEDIUM", "LOW"}
    get_settings.cache_clear()
