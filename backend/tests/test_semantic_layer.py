from src.context.semantic_layer import (
    append_semantic_to_rules,
    format_semantic_layer,
    parse_semantic_layer,
)


def test_parse_semantic_layer_empty():
    assert parse_semantic_layer(None) == {}
    assert parse_semantic_layer("") == {}
    assert parse_semantic_layer("not-json") == {}


def test_format_semantic_layer_metrics_and_synonyms():
    text = format_semantic_layer(
        {
            "metrics": [
                {
                    "name": "revenue",
                    "sql": "SUM(amount)",
                    "description": "completed only",
                }
            ],
            "synonyms": {"sales": "revenue"},
            "join_paths": ["orders.customer_id = customers.id"],
            "table_tiers": {"orders": "fact"},
        }
    )
    assert "SEMANTIC LAYER" in text
    assert "revenue" in text
    assert "SUM(amount)" in text
    assert "sales → revenue" in text
    assert "orders.customer_id" in text
    assert "orders: fact" in text


def test_format_semantic_layer_empty_returns_blank():
    assert format_semantic_layer({}) == ""
    assert format_semantic_layer({"metrics": []}) == ""


def test_format_semantic_layer_extended_fields():
    text = format_semantic_layer(
        {
            "relationships": [
                {
                    "from_table": "orders",
                    "from_col": "customer_id",
                    "to_table": "customers",
                    "to_col": "id",
                    "status": "approved",
                }
            ],
            "learned_conventions": ["Prefer completed orders"],
            "reviewed_queries": [{"question": "top customers", "sql": "SELECT 1"}],
            "repair_memory": [
                {
                    "error_pattern": "no such column",
                    "fix_hint": "use customer_id",
                    "sql_before": "SELECT x",
                    "sql_after": "SELECT customer_id",
                }
            ],
        }
    )
    assert "Relationships:" in text
    assert "orders.customer_id" in text
    assert "Prefer completed orders" in text
    assert "top customers" in text
    assert "no such column" in text


def test_append_semantic_to_rules():
    rules = "- Always filter status = completed"
    layer = '{"synonyms": {"gmv": "revenue"}}'
    out = append_semantic_to_rules(rules, layer)
    assert "Always filter" in out
    assert "gmv → revenue" in out

    only_layer = append_semantic_to_rules("(none)", layer)
    assert "gmv → revenue" in only_layer
    assert only_layer.startswith("━━━ SEMANTIC LAYER")
