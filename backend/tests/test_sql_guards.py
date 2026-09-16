from src.agent.nodes.query_validator import validate_syntax
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


def test_list_database_types_postgresql_only():
    types = list_database_types()
    assert types == ["postgresql"]
    assert "mysql" not in types
    assert "mssql" not in types
