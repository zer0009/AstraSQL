"""Portable project language: enrichments + rules + goldens. No LLM."""

from __future__ import annotations

from typing import Any, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from src.context.business_rules import BusinessRulesStore
from src.context.golden_records import GoldenRecordsStore
from src.context.schema_enrichment import SchemaEnrichmentStore

PACK_VERSION = 1


class PackDocument(TypedDict):
    version: int
    enrichments: list[dict[str, Any]]
    rules: list[dict[str, Any]]
    goldens: list[dict[str, Any]]


def _as_pack(raw: dict[str, Any]) -> PackDocument:
    version = int(raw.get("version") or PACK_VERSION)
    if version != PACK_VERSION:
        raise ValueError(f"Unsupported pack version: {version}")
    return {
        "version": version,
        "enrichments": list(raw.get("enrichments") or []),
        "rules": list(raw.get("rules") or []),
        "goldens": list(raw.get("goldens") or []),
    }


async def export_pack(session: AsyncSession, connection_id: str) -> PackDocument:
    enrichments = await SchemaEnrichmentStore().list(session, connection_id)
    rules = await BusinessRulesStore().list(session, connection_id)
    goldens = await GoldenRecordsStore().list(session, connection_id)
    return {
        "version": PACK_VERSION,
        "enrichments": [
            {
                "table_name": row.table_name,
                "column_name": row.column_name,
                "description": row.description,
                "alias": row.alias,
                "example_values": row.example_values,
            }
            for row in enrichments
        ],
        "rules": [{"content": row.content} for row in rules],
        "goldens": [{"question": row.question, "sql": row.sql} for row in goldens],
    }


async def import_pack(
    session: AsyncSession, connection_id: str, pack: dict[str, Any]
) -> dict[str, int]:
    document = _as_pack(pack)
    enrichment_store = SchemaEnrichmentStore()
    rules_store = BusinessRulesStore()
    golden_store = GoldenRecordsStore()

    enrich_count = 0
    for item in document["enrichments"]:
        table_name = str(item.get("table_name") or "").strip()
        if not table_name:
            continue
        column_name = item.get("column_name")
        if column_name is not None:
            column_name = str(column_name).strip() or None
        await enrichment_store.upsert(
            session,
            connection_id=connection_id,
            table_name=table_name,
            column_name=column_name,
            description=item.get("description"),
            alias=item.get("alias"),
            example_values=item.get("example_values"),
        )
        enrich_count += 1

    rule_count = 0
    for item in document["rules"]:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        await rules_store.create(session, connection_id, content)
        rule_count += 1

    golden_count = 0
    for item in document["goldens"]:
        question = str(item.get("question") or "").strip()
        sql = str(item.get("sql") or "").strip()
        if not question or not sql:
            continue
        await golden_store.add(session, connection_id, question, sql)
        golden_count += 1

    if golden_count:
        await golden_store.rebuild_index(session, connection_id)

    return {
        "enrichments": enrich_count,
        "rules": rule_count,
        "goldens": golden_count,
    }
