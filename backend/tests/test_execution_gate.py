from src.agent.execution_gate import (
    clause_diffs,
    cluster_by_results,
    decide_from_clusters,
)


def _res(rows, columns=None):
    cols = columns or [f"c{i}" for i in range(len(rows[0]) if rows else 0)]
    return {"columns": cols, "rows": rows, "row_count": len(rows)}


def test_cluster_by_results_groups_equal_denotations():
    candidates = [
        {"sql": "SELECT 1 AS a", "results": _res([[1]], ["a"])},
        {"sql": "SELECT 1 AS b", "results": _res([[1]], ["b"])},  # values equal
        {"sql": "SELECT 2 AS a", "results": _res([[2]], ["a"])},
        {"sql": "SELECT broken", "results": None},
    ]
    clusters = cluster_by_results(candidates)
    assert len(clusters) == 2
    sizes = sorted(len(c.member_indices) for c in clusters)
    assert sizes == [1, 2]


def test_decide_from_clusters_single_clear():
    clusters = cluster_by_results(
        [
            {"sql": "SELECT COUNT(*) FROM t", "results": _res([[5]], ["c"])},
            {"sql": "SELECT COUNT(*) FROM t WHERE 1=1", "results": _res([[5]], ["c"])},
        ]
    )
    decision = decide_from_clusters(clusters)
    assert decision.should_clarify is False
    assert decision.status == "clear"
    assert decision.selected_sql


def test_decide_from_clusters_split_asks():
    clusters = cluster_by_results(
        [
            {"sql": "SELECT SUM(a) FROM t", "results": _res([[10]], ["s"])},
            {"sql": "SELECT COUNT(*) FROM t", "results": _res([[3]], ["c"])},
        ]
    )
    decision = decide_from_clusters(clusters, dominance_threshold=0.99)
    assert decision.should_clarify is True
    assert decision.status == "ambiguous"
    assert decision.options


def test_decide_from_clusters_dominant_assumes():
    clusters = cluster_by_results(
        [
            {"sql": "SELECT SUM(a) FROM t", "results": _res([[10]], ["s"])},
            {"sql": "SELECT SUM(a) FROM t WHERE 1=1", "results": _res([[10]], ["s"])},
            {"sql": "SELECT SUM(a) FROM t WHERE a >= 0", "results": _res([[10]], ["s"])},
            {"sql": "SELECT COUNT(*) FROM t", "results": _res([[3]], ["c"])},
        ]
    )
    # Dominant mass = 3/4 = 0.75 >= 0.67
    decision = decide_from_clusters(clusters, dominance_threshold=0.67)
    assert decision.should_clarify is False
    assert decision.status == "assumed"


def test_decide_from_clusters_empty_failed_open():
    decision = decide_from_clusters([])
    assert decision.status == "failed_open"
    assert decision.should_clarify is False


def test_clause_diffs_detects_agg_and_where():
    diffs = clause_diffs(
        "SELECT SUM(amount) FROM orders WHERE status = 'paid'",
        "SELECT COUNT(*) FROM orders",
    )
    assert any("Aggregation" in d for d in diffs)
    assert any("WHERE" in d or "Filter" in d for d in diffs)


def test_clause_diffs_join_types():
    diffs = clause_diffs(
        "SELECT * FROM a JOIN b ON a.id = b.a_id",
        "SELECT * FROM a LEFT JOIN b ON a.id = b.a_id",
    )
    assert any("Join" in d for d in diffs)
