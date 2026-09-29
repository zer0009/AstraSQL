import pytest

from src.agent.nodes.query_validator import validate_syntax
from src.agent.sql_guards import find_bind_placeholders, refuse_unbound_sql
from src.agent.utils import classify_retry_type
from src.providers.database import list_database_types


def test_validate_syntax_allows_select():
    ok, err, is_dml = validate_syntax(
        "SELECT id, name FROM customers LIMIT 10",
        "postgres",
    )
    assert ok is True
    assert err is None
    assert is_dml is False


def test_validate_syntax_blocks_delete():
    ok, err, is_dml = validate_syntax("DELETE FROM customers WHERE id = 1", "postgres")
    assert ok is False
    assert is_dml is True
    assert err is not None
    assert "DML" in err


def test_validate_syntax_blocks_drop():
    ok, err, is_dml = validate_syntax("DROP TABLE customers", "postgres")
    assert ok is False
    assert is_dml is True
    assert err is not None


def test_find_bind_placeholders_detects_dollar():
    sql = (
        "SELECT e.name FROM employees e WHERE e.id = $1 "
        "AND lb.year = EXTRACT(YEAR FROM CURRENT_DATE)::integer"
    )
    assert find_bind_placeholders(sql) == ["$1"]


def test_find_bind_placeholders_detects_qmark_and_pyformat():
    assert "?" in find_bind_placeholders(
        "SELECT name FROM employees WHERE id = ?"
    )
    assert ":1" in find_bind_placeholders(
        "SELECT name FROM employees WHERE id = :1"
    )
    assert "%s" in find_bind_placeholders(
        "SELECT name FROM employees WHERE id = %s"
    )


def test_find_bind_placeholders_live_leave_balance():
    sql = (
        "SELECT e.name AS employee_name, lb.year, lt.code AS leave_type_code, "
        "lt.name AS leave_type_name, lbe.days AS available_days "
        "FROM leave_balances AS lb "
        "JOIN employees AS e ON lb.employee_id = e.id "
        "JOIN leave_balance_entries AS lbe ON lbe.balance_id = lb.id "
        "JOIN leave_types AS lt ON lbe.leave_type_id = lt.id "
        "WHERE lb.employee_id = $1 "
        "AND lb.year = EXTRACT(YEAR FROM CURRENT_DATE)::integer "
        "ORDER BY lt.name LIMIT 500"
    )
    assert find_bind_placeholders(sql) == ["$1"]
    with pytest.raises(ValueError, match="Unbound parameter"):
        refuse_unbound_sql(sql)


def test_find_bind_placeholders_ignores_pg_cast():
    assert find_bind_placeholders(
        "SELECT EXTRACT(YEAR FROM CURRENT_DATE)::integer"
    ) == []


def test_refuse_unbound_sql_blocks_live_leave_query():
    sql = (
        "SELECT e.name AS employee_name FROM users AS u "
        "JOIN employees AS e ON e.id = u.employee_id "
        "WHERE u.id = $1 AND lb.year = EXTRACT(YEAR FROM CURRENT_DATE)::integer"
    )
    with pytest.raises(ValueError, match="Unbound parameter \\$1"):
        refuse_unbound_sql(sql)


def test_refuse_unbound_sql_allows_casts():
    refuse_unbound_sql("SELECT EXTRACT(YEAR FROM CURRENT_DATE)::integer")


def test_validate_syntax_blocks_unbound_placeholder():
    ok, err, is_dml = validate_syntax(
        "SELECT name FROM employees WHERE id = $1",
        "postgres",
    )
    assert ok is False
    assert is_dml is False
    assert err is not None
    assert "$1" in err


def test_classify_retry_type_bind_parameter():
    assert (
        classify_retry_type(
            error="the server expects 1 argument for this query, 0 were passed"
        )
        == "BIND_PARAMETER"
    )
    assert (
        classify_retry_type(error="Unbound parameter $1: never emit placeholders")
        == "BIND_PARAMETER"
    )
    assert (
        classify_retry_type(
            error=(
                "EXPLAIN failed: (sqlalchemy.dialects.postgresql.asyncpg."
                "InterfaceError) the server expects 1 argument"
            )
        )
        == "BIND_PARAMETER"
    )


def test_list_database_types_postgresql_only():
    types = list_database_types()
    assert types == ["postgresql"]
    assert "mysql" not in types
    assert "mssql" not in types
