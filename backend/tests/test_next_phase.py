"""Unit tests for next-phase accuracy/speed hardening."""

from __future__ import annotations

from src.agent.ambiguity import (
    InterpretationCandidate,
    InterpretationProposal,
    apply_interpretation_policy,
)
from src.agent.difficulty_router import estimate_difficulty, route_generation_plan
from src.agent.result_shape import analyze_result_shape
from src.context.conventions import detect_join_type, join_type_convention_text
from src.context.value_grounding import match_literals_fuzzy, trigram_similarity
from src.eval.spider_data import TUNING_DB_IDS, pick_held_out
from src.observability.usage import latency_percentiles


def _shop():
    tables = {"customers", "orders"}
    pairs = {
        ("customers", "name"),
        ("customers", "id"),
        ("orders", "id"),
        ("orders", "customer_id"),
    }
    bare = {"name", "id", "customer_id"}
    return tables, pairs, bare


def test_single_candidate_reason_and_gate_defer():
    tables, pairs, bare = _shop()
    proposal = InterpretationProposal(
        status="ambiguous",
        assumption="",
        reason="one reading",
        candidates=(
            InterpretationCandidate(
                label="most orders",
                question="Which customer placed the most orders?",
                tables=("customers", "orders"),
                columns=("customers.name", "orders.id"),
            ),
            InterpretationCandidate(
                label="fake",
                question="Highest sales employee",
                tables=("employees",),
                columns=("employees.sales",),
            ),
        ),
    )
    decision = apply_interpretation_policy(
        proposal,
        question="best customer",
        tables=tables,
        column_pairs=pairs,
        bare_columns=bare,
        rules=[],
        golden_questions=[],
        defer_ask_to_execution_gate=True,
    )
    assert decision.should_clarify is False
    assert "single_candidate" in decision.decision_why
    assert decision.needs_execution_gate is True


def test_immaterial_defers_to_execution_gate():
    tables, pairs, bare = _shop()
    proposal = InterpretationProposal(
        status="ambiguous",
        assumption="",
        reason="phrasing",
        candidates=(
            InterpretationCandidate(
                label="a",
                question="Which customer placed the most orders?",
                tables=("customers", "orders"),
                columns=("customers.name", "orders.id"),
            ),
            InterpretationCandidate(
                label="b",
                question="Which customer placed the most orders via join?",
                tables=("customers", "orders"),
                columns=("customers.name", "orders.id"),
            ),
        ),
    )
    decision = apply_interpretation_policy(
        proposal,
        question="who placed the most orders",
        tables=tables,
        column_pairs=pairs,
        bare_columns=bare,
        rules=[],
        golden_questions=[],
        defer_ask_to_execution_gate=True,
    )
    assert decision.should_clarify is False
    assert "immaterial" in decision.decision_why
    assert decision.needs_execution_gate is True


def test_pick_by_knowns_does_not_treat_sole_candidate_as_known():
    tables, pairs, bare = _shop()
    proposal = InterpretationProposal(
        status="ambiguous",
        assumption="",
        reason="one",
        candidates=(
            InterpretationCandidate(
                label="most orders",
                question="Which customer placed the most orders?",
                tables=("customers", "orders"),
                columns=("customers.name", "orders.id"),
            ),
        ),
    )
    decision = apply_interpretation_policy(
        proposal,
        question="best customer",
        tables=tables,
        column_pairs=pairs,
        bare_columns=bare,
        rules=[],
        golden_questions=[],
        defer_ask_to_execution_gate=True,
    )
    assert "resolved_known" not in decision.decision_why
    assert "single_candidate" in decision.decision_why


def test_latency_percentiles():
    stats = latency_percentiles([10, 20, 30, 40, 100])
    assert stats["p50"] == 30
    assert stats["p95"] >= 40
    assert stats["mean"] > 0
    assert latency_percentiles([7])["p95"] == 7.0


def test_held_out_avoids_tuning_dbs():
    items = []
    for db in ("flight_2", "car_1", "orchestra"):
        for i in range(8):
            items.append(
                {
                    "db_id": db,
                    "question": f"{db} Q{i}",
                    "query": "SELECT COUNT(*) FROM t",
                }
            )
    assert "car_1" in TUNING_DB_IDS
    assert "orchestra" in TUNING_DB_IDS
    excluded = set(TUNING_DB_IDS)
    eligible = [x for x in items if x["db_id"] not in excluded]
    assert eligible
    assert all(x["db_id"] == "flight_2" for x in eligible)


def test_suspicious_all_null_triggers_retry():
    shape = analyze_result_shape(
        sql="SELECT a FROM t",
        results={
            "row_count": 2,
            "columns": ["a"],
            "rows": [{"a": None}, {"a": None}],
        },
        max_rows=100,
        retries=0,
    )
    assert "all_null" in shape["warnings"]
    assert shape["should_retry_suspicious"] is True


def test_difficulty_router():
    assert estimate_difficulty("How many singers?") == "simple"
    plan = route_generation_plan(
        "Compare revenue year over year for each region that also has never…",
        table_count=12,
        merge_interpret_generate=True,
    )
    assert plan["difficulty"] in {"moderate", "challenging"}
    assert plan["path"] in {"standard", "escalate"}


def test_trigram_fuzzy_match():
    assert trigram_similarity("california", "californai") > 0.4
    hints = match_literals_fuzzy(
        ["californai"],
        {"schools.county": ["California", "Oregon"]},
        min_score=0.4,
    )
    assert hints
    assert hints[0]["value"].lower().startswith("californ")


def test_join_convention():
    assert detect_join_type("SELECT * FROM a LEFT JOIN b ON a.id=b.id") == "left"
    assert "LEFT JOIN" in join_type_convention_text("left")


def test_relationship_lines_are_not_rule_conflicts():
    from src.agent.ambiguity import decide_ambiguity

    decision = decide_ambiguity(
        "List the vote ids of all votes",
        rules=[
            "VOTES.contestant_number = CONTESTANTS.contestant_number",
            "VOTES.contestant_number → CONTESTANTS.contestant_number [approved]",
        ],
        golden_questions=[],
    )
    assert decision.should_clarify is False
