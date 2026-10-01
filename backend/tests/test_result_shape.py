"""Result-shape heuristics after execute."""

from src.agent.graph import route_after_execute
from src.agent.result_shape import analyze_result_shape


def test_result_shape_empty_detection():
    shape = analyze_result_shape(
        sql="SELECT * FROM t WHERE id = 1",
        results={"columns": ["id"], "rows": [], "row_count": 0},
        max_rows=500,
        retries=0,
    )
    assert "empty_result" in shape["warnings"]
    assert shape["should_retry_empty"] is True
    assert shape["row_count"] == 0


def test_result_shape_empty_no_retry_after_first():
    shape = analyze_result_shape(
        sql="SELECT 1",
        results={"columns": ["x"], "rows": [], "row_count": 0},
        max_rows=500,
        retries=1,
    )
    assert "empty_result" in shape["warnings"]
    assert shape["should_retry_empty"] is False


def test_result_shape_duplicate_rows():
    rows = [{"a": 1, "b": 2}] * 4 + [{"a": 9, "b": 9}]
    shape = analyze_result_shape(
        sql="SELECT a, b FROM t WHERE x = 1",
        results={"columns": ["a", "b"], "rows": rows, "row_count": len(rows)},
        max_rows=500,
        retries=0,
    )
    assert "duplicate_rows" in shape["warnings"]
    assert shape["should_retry_empty"] is False


def test_result_shape_possible_cartesian():
    max_rows = 100
    rows = [{"id": i} for i in range(max_rows)]
    shape = analyze_result_shape(
        sql="SELECT * FROM a CROSS JOIN b",
        results={"columns": ["id"], "rows": rows, "row_count": max_rows},
        max_rows=max_rows,
        retries=0,
    )
    assert "possible_cartesian" in shape["warnings"]


def test_route_after_execute_shape_retry():
    assert (
        route_after_execute(
            {"shape_retry": True, "error": None, "retries": 0}
        )
        == "retry"
    )
    assert (
        route_after_execute(
            {"shape_retry": False, "error": None, "retries": 0}
        )
        == "format"
    )
