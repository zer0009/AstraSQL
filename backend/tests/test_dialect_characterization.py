"""Characterization: dialect must be threaded through SQL normalize / bind guards."""

from __future__ import annotations

import pytest

from src.agent.result_compare import sql_equal
from src.agent.sql_guards import find_bind_placeholders
from src.agent.trust import compute_trust_level, normalize_sql

_DIALECTS = ("postgres", "sqlite", "mysql")


@pytest.mark.parametrize("dialect", _DIALECTS)
def test_find_bind_placeholders_dollar_and_qmark(dialect: str):
    dollar = "SELECT name FROM employees WHERE id = $1"
    qmark = "SELECT name FROM employees WHERE id = ?"
    assert "$1" in find_bind_placeholders(dollar, dialect)
    assert "?" in find_bind_placeholders(qmark, dialect)


@pytest.mark.parametrize("dialect", _DIALECTS)
def test_normalize_sql_formatting_variants(dialect: str):
    a = "SELECT  amount FROM orders WHERE id = 1"
    b = "select amount from orders where id=1"
    assert normalize_sql(a, dialect) == normalize_sql(b, dialect)


@pytest.mark.parametrize("dialect", _DIALECTS)
def test_sql_equal_across_dialects(dialect: str):
    assert sql_equal(
        "SELECT COUNT(*) FROM customers",
        "select count(*) from customers",
        dialect,
    )


@pytest.mark.parametrize("dialect", _DIALECTS)
def test_compute_trust_level_certified_with_dialect(dialect: str):
    level = compute_trust_level(
        intent="SQL_QUERY",
        error=None,
        generated_sql="SELECT amount FROM orders",
        golden_sqls=["select  amount  from orders"],
        used_golden=True,
        dialect=dialect,
    )
    assert level == "certified"
