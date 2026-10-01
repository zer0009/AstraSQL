from src.context.value_grounding import (
    extract_literals,
    format_value_hints,
    match_literals_to_values,
)


def test_extract_literals_quoted_and_numbers():
    q = 'Show orders in "Texas" with status \'A\' totaling 42 items'
    lit = extract_literals(q)
    assert "Texas" in lit
    assert "A" in lit
    assert "42" in lit


def test_extract_literals_dedupes_case_insensitively():
    lit = extract_literals("Filter 'TX' and also 'tx'")
    assert lit.count("TX") + lit.count("tx") == 1


def test_match_literals_to_values_case_insensitive():
    index = {
        "customers.state": ["TX", "CA", "NY"],
        "orders.status": ["A", "I"],
    }
    hints = match_literals_to_values(["tx", "A"], index)
    assert any(
        h["table"] == "customers"
        and h["column"] == "state"
        and h["value"] == "TX"
        for h in hints
    )
    assert any(
        h["table"] == "orders" and h["column"] == "status" and h["value"] == "A"
        for h in hints
    )


def test_match_literals_empty_inputs():
    assert match_literals_to_values([], {"t.c": ["x"]}) == []
    assert match_literals_to_values(["x"], {}) == []


def test_format_value_hints_short_block():
    block = format_value_hints(
        [{"literal": "TX", "table": "customers", "column": "state", "value": "TX"}]
    )
    assert block.startswith("Value hints:")
    assert "customers.state" in block
    assert "TX" in block
