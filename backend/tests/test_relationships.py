"""Unit tests for relationship discovery and join-path helpers."""

from __future__ import annotations

import asyncio

from src.context.relationships import (
    discover_relationships,
    edges_to_semantic_join_paths,
    merge_relationship_edges,
    shortest_join_path,
)
from src.context.retriever import group_tables_by_pattern


def _run(coro):
    return asyncio.run(coro)


def test_discover_relationships_name_suffix_no_db():
    tables_data = [
        {
            "table_name": "customers",
            "columns": [
                {"name": "id", "type": "INTEGER", "primary_key": True},
                {"name": "name", "type": "TEXT"},
            ],
        },
        {
            "table_name": "orders",
            "columns": [
                {"name": "id", "type": "INTEGER", "primary_key": True},
                {"name": "customer_id", "type": "INTEGER"},
                {"name": "amount", "type": "REAL"},
            ],
        },
    ]
    edges = _run(discover_relationships(tables_data, db_provider=None, auto_approve=True))
    assert edges
    match = [
        e
        for e in edges
        if e["from_table"] == "orders"
        and e["from_col"] == "customer_id"
        and e["to_table"] == "customers"
    ]
    assert match, edges
    assert match[0]["to_col"].lower() == "id"
    assert match[0]["score"] >= 0.45
    assert "name_suffix" in match[0]["evidence"]


def test_discover_relationships_declared_fk_approved():
    tables_data = [
        {
            "table_name": "a",
            "columns": [
                {
                    "name": "b_id",
                    "type": "INT",
                    "foreign_key": {"table": "b", "column": "id"},
                }
            ],
        },
        {
            "table_name": "b",
            "columns": [{"name": "id", "type": "INT", "primary_key": True}],
        },
    ]
    edges = _run(discover_relationships(tables_data, auto_approve=False))
    assert any(
        e["status"] == "approved"
        and e["from_table"] == "a"
        and e["to_table"] == "b"
        and e["score"] == 1.0
        for e in edges
    )


def test_shortest_join_path_bridge():
    edges = [
        {
            "from_table": "orders",
            "from_col": "customer_id",
            "to_table": "customers",
            "to_col": "id",
            "status": "approved",
        },
        {
            "from_table": "order_items",
            "from_col": "order_id",
            "to_table": "orders",
            "to_col": "id",
            "status": "approved",
        },
    ]
    path = shortest_join_path(edges, ["order_items"], ["customers"])
    assert path
    tables_touched = {path[0][0], path[0][2]}
    for e in path[1:]:
        tables_touched.add(e[0])
        tables_touched.add(e[2])
    assert "orders" in tables_touched
    assert "customers" in tables_touched
    assert "order_items" in tables_touched


def test_shortest_join_path_already_connected():
    edges = [
        {
            "from_table": "a",
            "from_col": "b_id",
            "to_table": "b",
            "to_col": "id",
            "status": "approved",
        }
    ]
    assert shortest_join_path(edges, ["a", "b"], ["b"]) == []


def test_edges_to_semantic_join_paths():
    edges = [
        {
            "from_table": "orders",
            "from_col": "customer_id",
            "to_table": "customers",
            "to_col": "id",
            "status": "approved",
        }
    ]
    paths = edges_to_semantic_join_paths(edges)
    assert paths == ["orders.customer_id = customers.id"]


def test_merge_relationship_edges_preserves_approved():
    existing = [
        {
            "from_table": "a",
            "from_col": "b_id",
            "to_table": "b",
            "to_col": "id",
            "status": "approved",
            "score": 1.0,
        }
    ]
    discovered = [
        {
            "from_table": "a",
            "from_col": "b_id",
            "to_table": "b",
            "to_col": "id",
            "status": "proposed",
            "score": 0.5,
        }
    ]
    merged = merge_relationship_edges(existing, discovered)
    assert len(merged) == 1
    assert merged[0]["status"] == "approved"


def test_group_tables_by_pattern():
    groups = group_tables_by_pattern(
        ["sales_2020", "sales_2021", "customers", "orders_2022", "orders_2023"]
    )
    assert "sales" in groups
    assert set(groups["sales"]) == {"sales_2020", "sales_2021"}
    assert "orders" in groups
