"""Multi-candidate consensus selection (pure)."""

from src.agent.candidates import pick_consensus_sql


def test_candidate_consensus_picking():
    a = {
        "columns": ["n"],
        "rows": [{"n": 1}, {"n": 2}],
        "row_count": 2,
    }
    b = {
        "columns": ["cnt"],
        "rows": [{"cnt": 2}, {"cnt": 1}],
        "row_count": 2,
    }
    c = {
        "columns": ["n"],
        "rows": [{"n": 99}],
        "row_count": 1,
    }
    chosen = pick_consensus_sql(
        [
            {"sql": "SELECT n FROM t ORDER BY 1", "results": a},
            {"sql": "SELECT cnt FROM t2", "results": b},
            {"sql": "SELECT n FROM bad", "results": c},
        ]
    )
    # a and b match by values-only equality → consensus prefers that cluster.
    assert chosen in {
        "SELECT n FROM t ORDER BY 1",
        "SELECT cnt FROM t2",
    }


def test_candidate_consensus_sole_success():
    ok = {"columns": ["x"], "rows": [{"x": 1}], "row_count": 1}
    chosen = pick_consensus_sql(
        [
            {"sql": "SELECT bad", "results": None},
            {"sql": "SELECT x FROM t", "results": ok},
            {"sql": "SELECT worse", "results": None},
        ]
    )
    assert chosen == "SELECT x FROM t"


def test_candidate_consensus_all_failed_returns_none():
    assert (
        pick_consensus_sql(
            [
                {"sql": "SELECT 1", "results": None},
                {"sql": "SELECT 2", "results": None},
            ]
        )
        is None
    )
