import asyncio
import sqlite3
from pathlib import Path

import pytest

from src.providers.database.sqlite import SQLiteProvider, _quote_ident


@pytest.fixture()
def sqlite_file(tmp_path: Path) -> Path:
    path = tmp_path / "demo.sqlite"
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            'CREATE TABLE "singer info" ('
            "Singer_ID INTEGER PRIMARY KEY, "
            "Name TEXT, "
            "Country TEXT)"
        )
        conn.execute(
            'INSERT INTO "singer info" (Singer_ID, Name, Country) '
            "VALUES (1, 'A', 'US'), (2, 'B', 'UK')"
        )
        conn.execute(
            "CREATE TABLE album ("
            "Album_ID INTEGER PRIMARY KEY, "
            "Singer_ID INTEGER, "
            "Title TEXT, "
            "FOREIGN KEY (Singer_ID) REFERENCES \"singer info\"(Singer_ID))"
        )
        conn.execute(
            "INSERT INTO album (Album_ID, Singer_ID, Title) VALUES (1, 1, 'X')"
        )
        conn.commit()
    finally:
        conn.close()
    return path


def test_quote_ident_spaces():
    assert _quote_ident("singer info") == '"singer info"'
    # Always quote — reserved words like order/group break unquoted PRAGMA.
    assert _quote_ident("album") == '"album"'
    assert _quote_ident("order") == '"order"'


def test_list_and_schema(sqlite_file: Path):
    provider = SQLiteProvider(database=str(sqlite_file))

    async def _run():
        try:
            tables = await provider.list_tables()
            names = {t["name"] for t in tables}
            assert "singer info" in names
            assert "album" in names
            schema = await provider.get_table_schema("singer info")
            cols = {c["name"] for c in schema["columns"]}
            assert "Name" in cols
            assert schema["sample_rows"]
            ddl = await provider.get_table_ddl("album")
            assert "album" in ddl.lower()
            assert await provider.test_connection() is True
        finally:
            await provider.close()

    asyncio.run(_run())


def test_execute_readonly_and_limit(sqlite_file: Path):
    provider = SQLiteProvider(database=str(sqlite_file))

    async def _run():
        try:
            # Outer limit added when missing
            result = await provider.execute_readonly(
                'SELECT Name FROM "singer info"', max_rows=1
            )
            assert result["row_count"] == 1
            # CTE with inner LIMIT still wraps outer
            result2 = await provider.execute_readonly(
                'WITH t AS (SELECT Name FROM "singer info" LIMIT 1) '
                "SELECT * FROM t",
                max_rows=10,
            )
            assert result2["row_count"] >= 1
            plan = await provider.explain_query(
                'SELECT Name FROM "singer info" LIMIT 1'
            )
            assert plan
        finally:
            await provider.close()

    asyncio.run(_run())


def test_query_only_blocks_writes(sqlite_file: Path):
    provider = SQLiteProvider(database=str(sqlite_file))

    async def _run():
        try:
            from sqlalchemy.exc import SQLAlchemyError

            with pytest.raises((ValueError, RuntimeError, SQLAlchemyError)):
                await provider.execute_readonly(
                    'INSERT INTO "singer info" (Singer_ID, Name) VALUES (99, \'Z\')'
                )
        finally:
            await provider.close()

    asyncio.run(_run())


def test_missing_file_raises(tmp_path: Path):
    provider = SQLiteProvider(database=str(tmp_path / "missing.sqlite"))
    with pytest.raises(FileNotFoundError):
        provider.get_async_engine()
