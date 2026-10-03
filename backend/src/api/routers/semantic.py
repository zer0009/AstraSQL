"""Semantic layer, relationship approval, and dictionary import APIs."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import DbSession
from src.api.schemas import (
    DictionaryImportOut,
    DictionaryImportRequest,
    RelationshipStatusUpdate,
    SemanticLayerOut,
    SemanticRelationshipOut,
)
from src.context.dictionary_import import (
    import_dictionary_rows,
    parse_bird_description_csv,
    parse_dictionary_file,
)
from src.context.semantic_layer import parse_semantic_layer
from src.storage.models import Connection

router = APIRouter(tags=["semantic-layer"])


async def _get_connection(db: AsyncSession, connection_id: str) -> Connection:
    conn = await db.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


def _layer_out(connection: Connection) -> SemanticLayerOut:
    layer = parse_semantic_layer(getattr(connection, "semantic_layer_json", None))
    relationships: list[SemanticRelationshipOut] = []
    for edge in layer.get("relationships") or []:
        if not isinstance(edge, dict):
            continue
        ft = str(edge.get("from_table") or edge.get("left_table") or "").strip()
        fc = str(edge.get("from_col") or edge.get("left_column") or "").strip()
        tt = str(edge.get("to_table") or edge.get("right_table") or "").strip()
        tc = str(edge.get("to_col") or edge.get("right_column") or "").strip()
        if not (ft and fc and tt and tc):
            continue
        score = edge.get("score")
        relationships.append(
            SemanticRelationshipOut(
                from_table=ft,
                from_col=fc,
                to_table=tt,
                to_col=tc,
                status=str(edge.get("status") or "proposed"),
                score=float(score) if score is not None else None,
                evidence=str(edge.get("evidence") or "") or None,
            )
        )

    conventions = layer.get("learned_conventions") or []
    if not isinstance(conventions, list):
        conventions = []
    reviewed = layer.get("reviewed_queries") or []
    if not isinstance(reviewed, list):
        reviewed = []
    repair = layer.get("repair_memory") or []
    if not isinstance(repair, list):
        repair = []
    join_paths = layer.get("join_paths") or []
    if not isinstance(join_paths, list):
        join_paths = []

    return SemanticLayerOut(
        connection_id=connection.id,
        relationships=relationships,
        conventions=[str(c) for c in conventions if c],
        reviewed_queries=[r for r in reviewed if isinstance(r, dict)],
        repair_memory=[r for r in repair if isinstance(r, dict)],
        join_paths=[str(p) for p in join_paths if p],
        raw=layer,
    )


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(edge.get("from_table") or edge.get("left_table") or "").strip().lower(),
        str(edge.get("from_col") or edge.get("left_column") or "").strip().lower(),
        str(edge.get("to_table") or edge.get("right_table") or "").strip().lower(),
        str(edge.get("to_col") or edge.get("right_column") or "").strip().lower(),
    )


@router.get("/{connection_id}/semantic-layer", response_model=SemanticLayerOut)
async def get_semantic_layer(
    connection_id: str, db: DbSession
) -> SemanticLayerOut:
    connection = await _get_connection(db, connection_id)
    return _layer_out(connection)


@router.patch(
    "/{connection_id}/relationships/{from_table}/{from_col}/{to_table}/{to_col}",
    response_model=SemanticLayerOut,
)
async def update_relationship_status(
    connection_id: str,
    from_table: str,
    from_col: str,
    to_table: str,
    to_col: str,
    body: RelationshipStatusUpdate,
    db: DbSession,
) -> SemanticLayerOut:
    connection = await _get_connection(db, connection_id)
    layer = parse_semantic_layer(getattr(connection, "semantic_layer_json", None))
    edges = list(layer.get("relationships") or [])
    target = (
        from_table.strip().lower(),
        from_col.strip().lower(),
        to_table.strip().lower(),
        to_col.strip().lower(),
    )
    found = False
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if _edge_key(edge) == target:
            edge["status"] = body.status
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Relationship not found")

    join_paths: list[str] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if str(edge.get("status") or "").lower() != "approved":
            continue
        ft = str(edge.get("from_table") or "")
        fc = str(edge.get("from_col") or "")
        tt = str(edge.get("to_table") or "")
        tc = str(edge.get("to_col") or "")
        if ft and fc and tt and tc:
            join_paths.append(f"{ft}.{fc} = {tt}.{tc}")

    layer["relationships"] = edges
    layer["join_paths"] = join_paths
    connection.semantic_layer_json = json.dumps(layer)
    await db.commit()
    await db.refresh(connection)
    return _layer_out(connection)


@router.post(
    "/{connection_id}/dictionary-import",
    response_model=DictionaryImportOut,
)
async def import_dictionary(
    connection_id: str,
    body: DictionaryImportRequest,
    db: DbSession,
) -> DictionaryImportOut:
    await _get_connection(db, connection_id)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content must not be empty")

    with tempfile.TemporaryDirectory() as tmp:
        suffix = {
            "json": ".json",
            "csv": ".csv",
            "bird_csv": ".csv",
        }.get(body.format, ".json")
        path = Path(tmp) / f"dict{suffix}"
        path.write_text(content, encoding="utf-8")

        if body.format == "bird_csv":
            rows = parse_bird_description_csv(path)
            if body.table_name:
                for row in rows:
                    row["table_name"] = body.table_name
        else:
            rows = parse_dictionary_file(path)

        upserted = await import_dictionary_rows(db, connection_id, rows)
        return DictionaryImportOut(
            enrichments_created=upserted,
            enrichments_updated=0,
            rows_parsed=len(rows),
            message=f"Imported {len(rows)} dictionary rows ({upserted} upserted)",
        )


@router.post(
    "/{connection_id}/dictionary-upload",
    response_model=DictionaryImportOut,
)
async def upload_dictionary(
    connection_id: str,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    format: Annotated[str, Form()] = "json",
    table_name: Annotated[str | None, Form()] = None,
) -> DictionaryImportOut:
    await _get_connection(db, connection_id)
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="File must be UTF-8 text") from exc

    fmt = format if format in {"json", "csv", "bird_csv"} else "json"
    body = DictionaryImportRequest(
        format=fmt,  # type: ignore[arg-type]
        content=text,
        table_name=table_name,
    )
    return await import_dictionary(connection_id, body, db)
