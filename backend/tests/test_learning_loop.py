import asyncio

from src.context.learning_loop import (
    record_learned_convention,
    record_repair_memory,
    record_reviewed_query,
    retrieve_repair_hints,
    verify_repair_against_evidence,
)


def test_record_reviewed_query_dedupes():
    layer: dict = {}
    record_reviewed_query(layer, "How many orders?", "SELECT COUNT(*) FROM orders")
    record_reviewed_query(layer, "how many   orders?", "SELECT COUNT(*) FROM orders WHERE 1=1")
    assert len(layer["reviewed_queries"]) == 1
    assert "WHERE 1=1" in layer["reviewed_queries"][0]["sql"]


def test_record_repair_and_retrieve_hints():
    layer: dict = {}
    record_repair_memory(
        layer,
        error_pattern="missing join orders customers",
        fix_hint="Join orders to customers on customer_id",
        sql_before="SELECT * FROM orders",
        sql_after="SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id",
    )
    record_repair_memory(
        layer,
        error_pattern="wrong aggregate",
        fix_hint="Use SUM(amount) not COUNT(*)",
        sql_before="SELECT COUNT(*) FROM payments",
        sql_after="SELECT SUM(amount) FROM payments",
    )
    hints = retrieve_repair_hints(
        layer,
        "orders for customers",
        "SELECT * FROM orders",
        top_k=2,
    )
    assert hints
    assert any("Join" in h or "join" in h.lower() for h in hints)


def test_record_learned_convention():
    layer: dict = {}
    record_learned_convention(layer, "Revenue means SUM(amount) where status=paid")
    record_learned_convention(layer, "Revenue means SUM(amount) where status=paid")
    assert len(layer["learned_conventions"]) == 1


def test_verify_repair_against_evidence_ok():
    class _Ok:
        async def execute_readonly(self, sql, max_rows=1):
            return {"columns": ["x"], "rows": [[1]], "row_count": 1}

    assert asyncio.run(verify_repair_against_evidence(_Ok(), "SELECT 1")) is True


def test_verify_repair_against_evidence_fail():
    class _Bad:
        async def execute_readonly(self, sql, max_rows=1):
            raise RuntimeError("syntax error")

    assert asyncio.run(verify_repair_against_evidence(_Bad(), "SELECT bad")) is False
    assert asyncio.run(verify_repair_against_evidence(_Bad(), "")) is False
