"""Unit tests for deterministic SQLite SQL repairs (no DB)."""

from src.agent.sql_repair import (
    cast_integer_division,
    ensure_group_by_for_aggregates,
    repair_sqlite_sql,
)


def test_cast_integer_division_wraps_columns():
    sql = "SELECT a / b FROM t"
    out, changed = cast_integer_division(sql)
    assert changed is True
    assert "CAST" in out.upper()
    assert "REAL" in out.upper()
    assert "/" in out


def test_cast_integer_division_skips_already_cast():
    sql = "SELECT CAST(a AS REAL) / b FROM t"
    out, changed = cast_integer_division(sql)
    assert changed is False
    assert out == sql


def test_cast_integer_division_integer_literals():
    sql = "SELECT 1 / 2"
    out, changed = cast_integer_division(sql)
    assert changed is True
    assert "CAST" in out.upper()


def test_ensure_group_by_adds_missing_columns():
    sql = "SELECT name, COUNT(*) FROM users"
    out, changed = ensure_group_by_for_aggregates(sql)
    assert changed is True
    assert "GROUP BY" in out.upper()
    assert "name" in out.lower()


def test_ensure_group_by_skips_when_present():
    sql = "SELECT name, COUNT(*) FROM users GROUP BY name"
    out, changed = ensure_group_by_for_aggregates(sql)
    assert changed is False
    assert out == sql


def test_ensure_group_by_skips_no_aggregates():
    sql = "SELECT name, age FROM users"
    out, changed = ensure_group_by_for_aggregates(sql)
    assert changed is False


def test_repair_sqlite_sql_tags_division_and_groupby():
    sql = "SELECT dept, COUNT(*) , salary / headcount FROM emp"
    repaired, tags = repair_sqlite_sql(sql)
    assert "cast_integer_division" in tags
    assert "ensure_group_by_for_aggregates" in tags
    assert "CAST" in repaired.upper()
    assert "GROUP BY" in repaired.upper()


def test_repair_sqlite_sql_noop_on_clean():
    sql = "SELECT name FROM users WHERE id = 1"
    repaired, tags = repair_sqlite_sql(sql)
    assert tags == []
    assert repaired == sql
