import pytest

from src.agent.verified_cache import (
    find_verified_sql,
    normalize_question,
    token_overlap,
)
from src.storage.models import Connection, GoldenRecord


def test_normalize_question_collapses_punct_and_case():
    assert normalize_question("  How many Orders?! ") == "how many orders"
    assert normalize_question("A-B") == "a b"


def test_token_overlap_exact_and_near():
    assert token_overlap("total revenue by month", "total revenue by month") == 1.0
    near = token_overlap(
        "total revenue by month",
        "total revenue by month please",
    )
    assert near >= 0.8
    assert token_overlap("apples", "oranges") == 0.0
    assert token_overlap("", "x") == 0.0


@pytest.mark.asyncio
async def test_find_verified_sql_exact_and_overlap(db_session):
    conn = Connection(
        name="c",
        db_type="sqlite",
        host="local",
        port=0,
        database=":memory:",
        username="",
        encrypted_password="x",
    )
    db_session.add(conn)
    await db_session.flush()

    exact = GoldenRecord(
        connection_id=conn.id,
        question="How many customers?",
        sql="SELECT COUNT(*) FROM customers",
    )
    # 9/10 Jaccard = 0.9 — meets the default min_overlap gate.
    near = GoldenRecord(
        connection_id=conn.id,
        question="one two three four five six seven eight nine",
        sql="SELECT * FROM products WHERE active = 1",
    )
    db_session.add_all([exact, near])
    await db_session.flush()

    hit = await find_verified_sql(
        db_session, conn.id, "how many customers??", min_overlap=0.9
    )
    assert hit is not None
    assert hit.sql == exact.sql

    hit2 = await find_verified_sql(
        db_session,
        conn.id,
        "one two three four five six seven eight nine ten",
        min_overlap=0.9,
    )
    assert hit2 is not None
    assert "products" in hit2.sql

    miss = await find_verified_sql(
        db_session, conn.id, "unrelated weather query", min_overlap=0.9
    )
    assert miss is None
