"""Unit tests for agent overhaul fixes (gate reuse, diet, probes, stages)."""

from __future__ import annotations

import asyncio

import pytest

from src.agent.candidates import pick_consensus_sql
from src.agent.difficulty_router import route_generation_plan
from src.agent.empty_result_probe import should_retry_empty
from src.agent.execution_gate import cluster_by_results, decide_from_clusters
from src.agent.prompts.generator import format_conversation_history
from src.agent.utils import build_retry_context
from src.providers.llm.stages import resolve_max_tokens, resolve_reasoning_effort


def test_reasoning_effort_defaults_by_stage():
    assert resolve_reasoning_effort("intent_classifier") == "none"
    assert resolve_reasoning_effort("response_formatter") == "none"
    assert resolve_reasoning_effort("query_generator") in {
        "low",
        "medium",
        "high",
        "xhigh",
        "none",
        "",
    }
    assert resolve_reasoning_effort("repair_agent", escalate=True) == "medium"
    assert resolve_max_tokens("intent_classifier") <= 512
    assert resolve_max_tokens("query_generator") >= 1024


def test_difficulty_router_keeps_merged_schema_on_hard():
    plan = route_generation_plan(
        "Compare year over year ratio of customers who also never purchased",
        table_count=12,
        prior_failure=False,
        merge_interpret_generate=True,
        always_merged_schema=True,
    )
    assert plan["use_merge"] is True
    assert plan["candidate_count"] >= 1


def test_retry_context_does_not_accumulate():
    first = build_retry_context(
        previous_sql="SELECT 1",
        error="boom",
        prior_context="OLD CONTEXT THAT SHOULD BE DROPPED",
        retry_type="EMPTY_RESULT",
    )
    assert "OLD CONTEXT" not in first
    assert "EMPTY_RESULT" in first


def test_conversation_history_is_compact():
    text = format_conversation_history(
        [
            {
                "question": "How many orders?",
                "sql": "SELECT count(*) FROM orders",
                "answer": "There were " + ("many " * 80) + "orders in the result set.",
            }
        ]
    )
    assert "How many orders?" in text
    assert len(text) < 500


def test_pick_consensus_and_gate_reuse_seed_results():
    a = {"sql": "SELECT 1 AS x", "results": {"columns": ["x"], "rows": [[1]], "row_count": 1}}
    b = {"sql": "SELECT 1 AS y", "results": {"columns": ["y"], "rows": [[1]], "row_count": 1}}
    chosen = pick_consensus_sql([a, b])
    assert chosen in {"SELECT 1 AS x", "SELECT 1 AS y"}
    clusters = cluster_by_results([a, b])
    decision = decide_from_clusters(clusters, dominance_threshold=0.67)
    assert decision.should_clarify is False
    assert decision.selected_sql


def test_empty_result_probe_accepts_verified_empty():
    should, why = should_retry_empty(
        sql="SELECT * FROM t WHERE status = 'ZZZ_NOT_REAL'",
        question="rows with status ZZZ_NOT_REAL",
        context={
            "example_values": {"t": {"status": ["active", "closed"]}},
        },
        enabled=True,
    )
    # Literal not in samples → retry
    assert should is True
    assert "unverified" in why

    should2, why2 = should_retry_empty(
        sql="SELECT * FROM t WHERE status = 'active'",
        question="active rows",
        context={
            "example_values": {"t": {"status": ["active", "closed"]}},
        },
        enabled=True,
    )
    assert should2 is False
    assert "verified" in why2


@pytest.mark.asyncio
async def test_generate_candidates_reuses_seed_without_regen(monkeypatch):
    from src.agent import candidates as cand

    calls: list[str] = []

    async def fake_generate_one(**kwargs):
        calls.append(kwargs.get("variant") or "")
        return f"SELECT {len(calls)}"

    class FakeDb:
        def dialect_name(self):
            return "PostgreSQL"

        def dialect_prompt_rules(self):
            return ""

        async def execute_readonly(self, sql, max_rows=500):
            return {"columns": ["x"], "rows": [[1]], "row_count": 1}

    monkeypatch.setattr(cand, "_generate_one", fake_generate_one)
    sql, meta = await cand.generate_and_select_candidates(
        state={"context": {"enriched_schema": "CREATE TABLE t(x int);"}},
        config=None,
        db_provider=FakeDb(),
        settings=type(
            "S",
            (),
            {
                "max_result_rows": 50,
                "always_merged_schema": True,
                "merge_interpret_generate": True,
                "llm_max_tokens": 1024,
                "generator_max_tokens": 1024,
                "llm_reasoning_effort": "low",
                "generator_reasoning_effort": "",
                "repair_reasoning_effort": "medium",
                "intent_reasoning_effort": "none",
                "formatter_reasoning_effort": "none",
                "expansion_reasoning_effort": "none",
            },
        )(),
        candidate_count=1,
        question="count",
        seed_sql="SELECT 42",
        execute=False,
    )
    assert sql == "SELECT 42"
    assert calls == []
    assert meta["selected_by"] in {"single", "seed_only"}


def test_schema_text_cache_roundtrip():
    from src.context.retrieval.schema_text_cache import (
        get_cached_schema_text,
        invalidate_schema_text,
        set_cached_schema_text,
    )

    invalidate_schema_text()
    set_cached_schema_text("c1", "v1", "CREATE TABLE t(id int);")
    assert get_cached_schema_text("c1", "v1") == "CREATE TABLE t(id int);"
    assert get_cached_schema_text("c1", "v2") is None
    invalidate_schema_text("c1")
    assert get_cached_schema_text("c1", "v1") is None


def test_snapshot_refine_disables_clarify():
    from src.storage.repositories.snapshots import snapshot_to_state

    class Row:
        id = "run-1"
        connection_id = "c1"
        question = "how many orders?"
        context_json = '{"enriched_schema":"CREATE TABLE orders(id int);"}'
        alternatives_json = '["count all","count completed"]'
        ambiguity_json = None
        assumption = "count all orders"
        sql = "SELECT count(*) FROM orders"

    state = snapshot_to_state(Row())  # type: ignore[arg-type]
    assert state["allow_clarify"] is False
    assert state["run_id"] == "run-1"
    assert "count all" in (state.get("clarification_options") or [])


@pytest.mark.asyncio
async def test_executor_skips_reexecution_when_cached():
    from src.agent.nodes.query_executor import query_executor

    calls: list[str] = []

    class FakeDb:
        def sqlglot_dialect(self):
            return "postgres"

        def supports_explain(self):
            return False

        async def execute_readonly(self, sql, max_rows=500):
            calls.append(sql)
            return {"columns": ["x"], "rows": [[9]], "row_count": 1}

        async def explain_query(self, sql):
            calls.append("explain:" + sql)
            return "ok"

    state = {
        "sql": "SELECT 1",
        "results": {"columns": ["x"], "rows": [[1]], "row_count": 1},
        "cached_execution": True,
        "retries": 0,
        "steps": [],
    }
    config = {"configurable": {"db_provider": FakeDb()}}
    out = await query_executor(state, config)  # type: ignore[arg-type]
    assert calls == []
    assert out["results"]["row_count"] == 1
    assert any(
        s.get("name") == "query_executed" for s in (out.get("steps") or [])
    ) or "Reused" in str(out.get("steps"))


@pytest.mark.asyncio
async def test_golden_min_score_filters():
    """GoldenRecordsStore.search drops hits below min_score."""
    import numpy as np

    from src.context.golden_records import GoldenRecordsStore

    class FakeIndex:
        ntotal = 2

        def search(self, query, k):
            return np.array([[0.9, 0.2]], dtype=np.float32), np.array(
                [[0, 1]], dtype=np.int64
            )

    store = GoldenRecordsStore.__new__(GoldenRecordsStore)
    store._settings = type(
        "S", (), {"golden_records_top_k": 5, "golden_min_score": 0.45}
    )()
    store._load_index = lambda _cid: (FakeIndex(), ["id-hi", "id-lo"])  # type: ignore[method-assign]

    class FakeSession:
        async def get(self, _model, record_id):
            return type(
                "R",
                (),
                {
                    "id": record_id,
                    "question": f"q-{record_id}",
                    "sql": f"SELECT '{record_id}'",
                },
            )()

    hits = await store.search(
        FakeSession(),  # type: ignore[arg-type]
        "c1",
        "question",
        min_score=0.45,
        query_vector=np.ones((1, 8), dtype=np.float32),
    )
    assert len(hits) == 1
    assert hits[0]["id"] == "id-hi"
