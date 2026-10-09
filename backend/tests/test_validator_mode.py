"""validator_mode: full | deterministic | off — LLM skip branches."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.nodes.query_validator import check_catalog, query_validator
from src.config.settings import get_settings


class _FakeDb:
    def sqlglot_dialect(self) -> str:
        return "postgres"

    def dialect_name(self) -> str:
        return "PostgreSQL"

    def dialect_validator_checklist(self) -> list[str]:
        return []


def _config():
    return {"configurable": {"db_provider": _FakeDb()}}


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_validator_mode_skips_llm(monkeypatch):
    monkeypatch.setenv("VALIDATOR_MODE", "off")
    get_settings.cache_clear()

    llm_factory = MagicMock()
    with patch(
        "src.agent.nodes.query_validator.get_llm_provider",
        return_value=MagicMock(get_chat_model=llm_factory),
    ):
        out = await query_validator(
            {
                "sql": "SELECT id FROM customers",
                "question": "list customer ids",
                "context": {},
                "retries": 0,
            },
            _config(),
        )

    assert out.get("error") is None
    assert out.get("sql") == "SELECT id FROM customers"
    llm_factory.assert_not_called()
    steps = out.get("steps") or []
    assert steps
    assert steps[-1].get("validator_mode") == "off"
    assert "LLM skipped" in (steps[-1].get("detail") or "")


@pytest.mark.asyncio
async def test_validator_mode_deterministic_skips_llm(monkeypatch):
    monkeypatch.setenv("VALIDATOR_MODE", "deterministic")
    get_settings.cache_clear()

    llm_factory = MagicMock()
    with patch(
        "src.agent.nodes.query_validator.get_llm_provider",
        return_value=MagicMock(get_chat_model=llm_factory),
    ):
        out = await query_validator(
            {
                "sql": "SELECT id FROM customers",
                "question": "list ids",
                "context": {
                    "selected_tables": ["customers"],
                    "selected_columns": [
                        {"table": "customers", "column": "id"},
                    ],
                },
                "retries": 0,
            },
            _config(),
        )

    assert out.get("error") is None
    llm_factory.assert_not_called()
    assert (out.get("steps") or [])[-1].get("validator_mode") == "deterministic"


@pytest.mark.asyncio
async def test_validator_mode_full_calls_llm(monkeypatch):
    monkeypatch.setenv("VALIDATOR_MODE", "full")
    get_settings.cache_clear()

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"is_valid": true, "issues_found": [], '
            '"corrected_sql": "SELECT id FROM customers", "error_type": null}'
        )
    )
    with patch(
        "src.agent.nodes.query_validator.get_llm_provider",
        return_value=MagicMock(get_chat_model=MagicMock(return_value=mock_llm)),
    ):
        out = await query_validator(
            {
                "sql": "SELECT id FROM customers",
                "question": "list ids",
                "context": {"enriched_schema": "CREATE TABLE customers (id int);"},
                "retries": 0,
            },
            _config(),
        )

    assert out.get("error") is None
    mock_llm.ainvoke.assert_awaited()


def test_check_catalog_flags_unknown_table():
    issues = check_catalog(
        "SELECT id FROM orders",
        "postgres",
        selected_tables=["customers"],
        selected_columns=[{"table": "customers", "column": "id"}],
    )
    assert any("orders" in i.lower() for i in issues)


def test_check_catalog_allows_ctes_and_selected_table_columns():
    sql = """
    WITH monthly_quantities AS (
        SELECT
            DATE_TRUNC('month', po.create_date)::date AS purchase_month,
            SUM(pol.product_qty) AS total_purchased_quantity
        FROM purchase_order po
        JOIN purchase_order_line pol ON pol.order_id = po.id
        WHERE pol.display_type IS NULL
        GROUP BY 1
    ),
    with_changes AS (
        SELECT
            purchase_month,
            total_purchased_quantity,
            LAG(total_purchased_quantity) OVER (ORDER BY purchase_month)
                AS previous_month_quantity
        FROM monthly_quantities
    )
    SELECT purchase_month, total_purchased_quantity, previous_month_quantity
    FROM with_changes
    ORDER BY purchase_month
    """
    issues = check_catalog(
        sql,
        "postgres",
        selected_tables=["purchase_order", "purchase_order_line"],
        # Sparse linker list (huge-schema PK/FK expansion) — must not reject
        # real columns that appear in the enriched schema text.
        selected_columns=[
            {"table": "purchase_order", "column": "id"},
            {"table": "purchase_order_line", "column": "id"},
            {"table": "purchase_order_line", "column": "order_id"},
        ],
    )
    assert issues == []
