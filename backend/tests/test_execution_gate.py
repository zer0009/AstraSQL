from src.agent.execution_gate import (
    clause_diffs,
    cluster_by_results,
    decide_from_clusters,
    is_generic_gate_option,
    options_from_clusters,
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


def test_options_from_clusters_uses_group_by_labels():
    clusters = cluster_by_results(
        [
            {
                "sql": (
                    "SELECT country, SUM(qty) AS q FROM sales "
                    "GROUP BY country"
                ),
                "results": _res([["SA", 10]], ["country", "q"]),
            },
            {
                "sql": (
                    "SELECT country, state, SUM(qty) AS q FROM sales "
                    "GROUP BY country, state"
                ),
                "results": _res([["SA", "Riyadh", 4]], ["country", "state", "q"]),
            },
        ]
    )
    options = options_from_clusters(clusters, dialect="postgres")
    assert any("Group by" in o and "country" in o.lower() for o in options)
    assert any(o.lower().startswith("other") for o in options)
    assert not any(
        is_generic_gate_option(o)
        for o in options
        if not o.lower().startswith("other")
    )
    # Must not push raw *_id identifiers into the next user turn.
    assert not any("country_id" in o for o in options)


def test_options_from_clusters_postgres_json_dialect():
    """Wrong dialect used to yield only 'Different SQL implementations'."""
    clusters = cluster_by_results(
        [
            {
                "sql": (
                    "SELECT rc.name->>'en_US' AS country, SUM(s.qty) "
                    "FROM sales s JOIN res_country rc ON s.country_id = rc.id "
                    "GROUP BY rc.name->>'en_US'"
                ),
                "results": _res([["SA", 10]], ["country", "sum"]),
            },
            {
                "sql": (
                    "SELECT rc.name->>'en_US' AS country, "
                    "rcs.name->>'en_US' AS state, SUM(s.qty) "
                    "FROM sales s "
                    "JOIN res_country rc ON s.country_id = rc.id "
                    "JOIN res_country_state rcs ON s.state_id = rcs.id "
                    "GROUP BY rc.name->>'en_US', rcs.name->>'en_US'"
                ),
                "results": _res([["SA", "Riyadh", 4]], ["country", "state", "sum"]),
            },
        ]
    )
    options = options_from_clusters(clusters, dialect="postgres")
    assert len(options) >= 2
    assert not any("Different SQL implementations" in o for o in options)
    assert any("Group by" in o for o in options)


def test_readings_map_choice_to_full_sql():
    from src.agent.execution_gate import readings_from_clusters, resolve_reading_sql

    clusters = cluster_by_results(
        [
            {
                "sql": (
                    "SELECT COALESCE(NULLIF(rc.code, ''), 'x') AS country_code, "
                    "SUM(1) FROM sales s JOIN res_country rc ON s.country_id = rc.id "
                    "GROUP BY COALESCE(NULLIF(rc.code, ''), 'x')"
                ),
                "results": _res([["SA", 10]], ["country_code", "sum"]),
            },
            {
                "sql": (
                    "SELECT COALESCE(NULLIF(rc.code, ''), 'x') AS country_code, "
                    "rcs.code AS state_code, SUM(1) FROM sales s "
                    "JOIN res_country rc ON s.country_id = rc.id "
                    "JOIN res_country_state rcs ON s.state_id = rcs.id "
                    "GROUP BY COALESCE(NULLIF(rc.code, ''), 'x'), rcs.code"
                ),
                "results": _res([["SA", "01", 4]], ["country_code", "state_code", "sum"]),
            },
        ]
    )
    readings = readings_from_clusters(clusters, dialect="postgres")
    assert len(readings) >= 2
    for r in readings:
        assert "')" not in r["label"]
        assert "GROUP BY" in r["sql"].upper() or "group by" in r["sql"].lower()
    matched = resolve_reading_sql(readings[1]["label"], readings)
    assert matched == readings[1]["sql"]


def test_decide_from_clusters_stores_readings():
    clusters = cluster_by_results(
        [
            {
                "sql": "SELECT country, SUM(qty) FROM t GROUP BY country",
                "results": _res([["SA", 1]], ["country", "sum"]),
            },
            {
                "sql": "SELECT country, state, SUM(qty) FROM t GROUP BY country, state",
                "results": _res([["SA", "R", 1]], ["country", "state", "sum"]),
            },
        ]
    )
    decision = decide_from_clusters(clusters, dominance_threshold=0.99)
    assert decision.readings
    assert all(r.get("sql") for r in decision.readings)
    assert len(decision.readings[0]["sql"]) == len(
        "SELECT country, SUM(qty) FROM t GROUP BY country"
    ) or decision.readings[0]["sql"].startswith("SELECT")
