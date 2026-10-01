from src.eval.compare import (
    gold_has_order_by,
    results_equal,
    results_equal_values,
    sql_equal,
)
from src.eval.models import CaseResult
from src.eval.run import build_report


def test_sql_equal_ignores_whitespace_and_case():
    assert sql_equal("SELECT COUNT(*) FROM customers", "select count(*) from customers")


def test_sql_equal_false_on_empty():
    assert sql_equal("", "SELECT 1") is False


def test_results_equal_ignores_column_case_and_row_order():
    left = {
        "columns": ["Name", "N"],
        "rows": [{"Name": "Alice", "N": 2}, {"Name": "Bob", "N": 1}],
    }
    right = {
        "columns": ["n", "name"],
        "rows": [{"name": "Bob", "n": 1}, {"name": "Alice", "n": 2}],
    }
    assert results_equal(left, right) is True


def test_results_equal_detects_value_mismatch():
    left = {"columns": ["n"], "rows": [{"n": 3}]}
    right = {"columns": ["n"], "rows": [{"n": 4}]}
    assert results_equal(left, right) is False


def test_results_equal_values_ignores_alias():
    gold = {
        "columns": ["country", "count(*)"],
        "rows": [{"country": "France", "count(*)": 2}, {"country": "Netherlands", "count(*)": 1}],
    }
    gen = {
        "columns": ["country", "singer_count"],
        "rows": [
            {"country": "Netherlands", "singer_count": 1},
            {"country": "France", "singer_count": 2},
        ],
    }
    assert results_equal(gold, gen) is False
    assert results_equal_values(gold, gen) is True


def test_results_equal_values_different_row_counts_fail():
    gold = {"columns": ["n"], "rows": [{"n": 1}, {"n": 2}]}
    gen = {"columns": ["n"], "rows": [{"n": 1}, {"n": 2}, {"n": 0}]}
    assert results_equal_values(gold, gen) is False


def test_results_equal_values_left_join_extra_rows_fail():
    gold = {
        "columns": ["name", "c"],
        "rows": [{"name": "A", "c": 2}, {"name": "B", "c": 1}],
    }
    gen = {
        "columns": ["name", "c"],
        "rows": [
            {"name": "A", "c": 2},
            {"name": "B", "c": 1},
            {"name": "C", "c": 0},
        ],
    }
    assert results_equal_values(gold, gen) is False


def test_results_equal_values_order_sensitive_with_order_by():
    gold_sql = "SELECT name FROM t ORDER BY name"
    gold = {"columns": ["name"], "rows": [{"name": "A"}, {"name": "B"}]}
    gen = {"columns": ["name"], "rows": [{"name": "B"}, {"name": "A"}]}
    assert results_equal_values(gold, gen, gold_sql=gold_sql) is False
    assert results_equal_values(gold, gen, gold_sql="SELECT name FROM t") is True
    assert gold_has_order_by(gold_sql) is True


def test_results_equal_values_float_tolerance():
    gold = {"columns": ["x"], "rows": [{"x": 1.0}]}
    gen = {"columns": ["x"], "rows": [{"x": 1.0000001}]}
    assert results_equal_values(gold, gen) is True


def test_build_report_rates():
    cases = [
        CaseResult(
            id="a1",
            question="q",
            expect="answer",
            sql_match=True,
            result_match=True,
        ),
        CaseResult(
            id="a2",
            question="q",
            expect="answer",
            sql_match=False,
            result_match=False,
        ),
        CaseResult(
            id="c1",
            question="revenue",
            expect="clarify",
            clarified=True,
            silent_wrong=False,
        ),
        CaseResult(
            id="c2",
            question="revenue",
            expect="clarify",
            clarified=False,
            silent_wrong=True,
        ),
    ]
    report = build_report(
        cases,
        model="gpt-4o",
        gold_path="gold.json",
        connection_id="c1",
    )
    assert report.n == 4
    assert report.execution_match == 0.5
    assert report.sql_match_rate == 0.5
    assert report.clarify_hit == 0.5
    assert report.silent_wrong == 0.5
