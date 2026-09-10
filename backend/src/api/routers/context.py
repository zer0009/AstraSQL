from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from src.api.deps import DbSession
from src.api.schemas import (
    BusinessRuleCreate,
    BusinessRuleOut,
    BusinessRuleUpdate,
    EnrichmentCreate,
    EnrichmentOut,
    EnrichmentUpdate,
    GoldenRecordCreate,
    GoldenRecordOut,
)
from src.context import BusinessRulesStore, GoldenRecordsStore, SchemaEnrichmentStore
from src.storage.models import BusinessRule, Connection, GoldenRecord, SchemaEnrichment

router = APIRouter(tags=["context"])

enrichment_store = SchemaEnrichmentStore()
golden_store = GoldenRecordsStore()
rules_store = BusinessRulesStore()


def _serialize_example_values(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


async def _ensure_connection(db: DbSession, connection_id: str) -> None:
    if await db.get(Connection, connection_id) is None:
        raise HTTPException(status_code=404, detail="Connection not found")


# --- Enrichments -----------------------------------------------------------


@router.get("/enrichments", response_model=list[EnrichmentOut])
async def list_enrichments(
    db: DbSession,
    connection_id: str = Query(...),
) -> list[SchemaEnrichment]:
    await _ensure_connection(db, connection_id)
    return await enrichment_store.list(db, connection_id)


@router.post("/enrichments", response_model=EnrichmentOut, status_code=201)
async def create_enrichment(body: EnrichmentCreate, db: DbSession) -> SchemaEnrichment:
    await _ensure_connection(db, body.connection_id)
    return await enrichment_store.upsert(
        db,
        connection_id=body.connection_id,
        table_name=body.table_name,
        column_name=body.column_name,
        description=body.description,
        alias=body.alias,
        example_values=_serialize_example_values(body.example_values),
    )


@router.put("/enrichments/{enrichment_id}", response_model=EnrichmentOut)
async def update_enrichment(
    enrichment_id: str, body: EnrichmentUpdate, db: DbSession
) -> SchemaEnrichment:
    row = await db.get(SchemaEnrichment, enrichment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Enrichment not found")

    data = body.model_dump(exclude_unset=True)
    if "example_values" in data:
        data["example_values"] = _serialize_example_values(data["example_values"])

    for field, value in data.items():
        setattr(row, field, value)

    await db.flush()
    return row


@router.delete("/enrichments/{enrichment_id}", status_code=204)
async def delete_enrichment(enrichment_id: str, db: DbSession) -> None:
    deleted = await enrichment_store.delete(db, enrichment_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Enrichment not found")


# --- Golden records --------------------------------------------------------


@router.get("/golden-records", response_model=list[GoldenRecordOut])
async def list_golden_records(
    db: DbSession,
    connection_id: str = Query(...),
) -> list[GoldenRecord]:
    await _ensure_connection(db, connection_id)
    return await golden_store.list(db, connection_id)


@router.post("/golden-records", response_model=GoldenRecordOut, status_code=201)
async def create_golden_record(
    body: GoldenRecordCreate, db: DbSession
) -> GoldenRecord:
    await _ensure_connection(db, body.connection_id)
    return await golden_store.add(
        db,
        connection_id=body.connection_id,
        question=body.question,
        sql=body.sql,
    )


@router.delete("/golden-records/{record_id}", status_code=204)
async def delete_golden_record(record_id: str, db: DbSession) -> None:
    deleted = await golden_store.delete(db, record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Golden record not found")


# --- Business rules --------------------------------------------------------


@router.get("/rules", response_model=list[BusinessRuleOut])
async def list_rules(
    db: DbSession,
    connection_id: str = Query(...),
) -> list[BusinessRule]:
    await _ensure_connection(db, connection_id)
    return await rules_store.list(db, connection_id)


@router.post("/rules", response_model=BusinessRuleOut, status_code=201)
async def create_rule(body: BusinessRuleCreate, db: DbSession) -> BusinessRule:
    await _ensure_connection(db, body.connection_id)
    return await rules_store.create(db, body.connection_id, body.content)


@router.put("/rules/{rule_id}", response_model=BusinessRuleOut)
async def update_rule(
    rule_id: str, body: BusinessRuleUpdate, db: DbSession
) -> BusinessRule:
    row = await rules_store.update(db, rule_id, body.content)
    if row is None:
        raise HTTPException(status_code=404, detail="Business rule not found")
    return row


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: str, db: DbSession) -> None:
    deleted = await rules_store.delete(db, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Business rule not found")
