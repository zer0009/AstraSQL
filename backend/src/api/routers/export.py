from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook

from src.api.schemas import ExportRequest

router = APIRouter(tags=["export"])

_CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json; charset=utf-8",
}


def _row_as_list(columns: list[str], row: dict[str, Any] | list[Any]) -> list[Any]:
    if isinstance(row, dict):
        return [row.get(col) for col in columns]
    return list(row)


def _default_filename(fmt: str) -> str:
    return f"export.{fmt}"


@router.post("")
async def export_data(body: ExportRequest) -> StreamingResponse:
    if body.format not in _CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="format must be csv, xlsx, or json")

    filename = body.filename or _default_filename(body.format)
    if not filename.lower().endswith(f".{body.format}"):
        filename = f"{filename}.{body.format}"

    if body.format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(body.columns)
        for row in body.rows:
            writer.writerow(_row_as_list(body.columns, row))
        payload = io.BytesIO(buffer.getvalue().encode("utf-8"))
    elif body.format == "json":
        if body.rows and isinstance(body.rows[0], dict):
            data: Any = body.rows
        else:
            data = [
                dict(zip(body.columns, _row_as_list(body.columns, row)))
                for row in body.rows
            ]
        payload = io.BytesIO(
            json.dumps(data, default=str, ensure_ascii=False, indent=2).encode("utf-8")
        )
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "export"
        ws.append(body.columns)
        for row in body.rows:
            ws.append(_row_as_list(body.columns, row))
        payload = io.BytesIO()
        wb.save(payload)
        payload.seek(0)

    payload.seek(0)
    return StreamingResponse(
        payload,
        media_type=_CONTENT_TYPES[body.format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
