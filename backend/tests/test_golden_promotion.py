"""Unit tests for golden promotion service (gates + dedup)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services import golden_promotion as gp


@pytest.mark.asyncio
async def test_find_duplicate_golden_matches_normalized_question():
    rows = [
        SimpleNamespace(question="How many orders?"),
        SimpleNamespace(question="other"),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    found = await gp.find_duplicate_golden(db, "conn-1", "how many orders?")
    assert found is rows[0]


@pytest.mark.asyncio
async def test_find_duplicate_golden_none_when_empty_norm():
    db = AsyncMock()
    assert await gp.find_duplicate_golden(db, "conn-1", "   ") is None
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_promote_golden_rejects_empty_sql():
    db = AsyncMock()
    out = await gp.promote_golden(
        db, connection_id="c1", question="q", sql="  "
    )
    assert out is None


@pytest.mark.asyncio
async def test_promote_golden_returns_existing_duplicate(monkeypatch):
    existing = SimpleNamespace(id="g1", question="q")
    monkeypatch.setattr(
        gp, "find_duplicate_golden", AsyncMock(return_value=existing)
    )
    store = MagicMock()
    store.add = AsyncMock()
    out = await gp.promote_golden(
        db=AsyncMock(),
        connection_id="c1",
        question="q",
        sql="SELECT 1",
        golden_store=store,
    )
    assert out is existing
    store.add.assert_not_called()


@pytest.mark.asyncio
async def test_promote_golden_skips_execute_gate_for_mysql(monkeypatch):
    monkeypatch.setattr(gp, "find_duplicate_golden", AsyncMock(return_value=None))
    try_exec = AsyncMock(return_value=True)
    monkeypatch.setattr(gp, "try_execute_readonly", try_exec)

    conn = SimpleNamespace(id="c1", db_type="mysql")
    db = AsyncMock()
    db.get = AsyncMock(return_value=conn)

    created = SimpleNamespace(id="g-new")
    store = MagicMock()
    store.add = AsyncMock(return_value=created)
    store.rebuild_index = AsyncMock()

    out = await gp.promote_golden(
        db,
        connection_id="c1",
        question="q",
        sql="SELECT 1",
        golden_store=store,
    )
    assert out is created
    try_exec.assert_not_called()
    store.add.assert_awaited_once()
    store.rebuild_index.assert_awaited_once()


@pytest.mark.asyncio
async def test_promote_golden_runs_execute_gate_for_postgres(monkeypatch):
    monkeypatch.setattr(gp, "find_duplicate_golden", AsyncMock(return_value=None))
    try_exec = AsyncMock(return_value=True)
    monkeypatch.setattr(gp, "try_execute_readonly", try_exec)

    conn = SimpleNamespace(id="c1", db_type="postgresql")
    db = AsyncMock()
    db.get = AsyncMock(return_value=conn)

    created = SimpleNamespace(id="g-new")
    store = MagicMock()
    store.add = AsyncMock(return_value=created)
    store.rebuild_index = AsyncMock()

    out = await gp.promote_golden(
        db,
        connection_id="c1",
        question="q",
        sql="SELECT 1",
        golden_store=store,
    )
    assert out is created
    try_exec.assert_awaited_once_with(conn, "SELECT 1")
