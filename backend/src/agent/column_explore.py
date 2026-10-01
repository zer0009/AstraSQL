"""Bounded column exploration for repair / grounding context."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def explore_column(
    db_provider: Any,
    table: str,
    column: str,
    *,
    max_distinct: int = 20,
) -> dict:
    """Sample distinct values and a null/row probe for one column.

    Returns::

        {
          "table": ..., "column": ...,
          "distinct_values": [...],
          "null_count_estimate": int | None,
          "row_probe": int | None,
          "error": str | None,
        }
    """
    out: dict[str, Any] = {
        "table": table,
        "column": column,
        "distinct_values": [],
        "null_count_estimate": None,
        "row_probe": None,
        "error": None,
    }
    if db_provider is None or not table or not column:
        out["error"] = "missing provider/table/column"
        return out

    quote = getattr(db_provider, "quote_ident", None)

    def q(name: str) -> str:
        if callable(quote):
            try:
                return str(quote(name))
            except Exception:
                pass
        return name

    tq, cq = q(table), q(column)
    lim = max(1, int(max_distinct))

    try:
        # Distinct sample
        if hasattr(db_provider, "sample_distinct_values"):
            values = await db_provider.sample_distinct_values(table, column, limit=lim)
            out["distinct_values"] = list(values or [])[:lim]
        else:
            sql = (
                f"SELECT DISTINCT {cq} AS v FROM {tq} "
                f"WHERE {cq} IS NOT NULL LIMIT {lim}"
            )
            result = await db_provider.execute_readonly(sql, max_rows=lim)
            vals: list[Any] = []
            for row in result.get("rows") or []:
                if isinstance(row, dict):
                    raw = row.get("v")
                    if raw is None and row:
                        raw = next(iter(row.values()), None)
                else:
                    raw = row
                if raw is not None:
                    vals.append(raw)
            out["distinct_values"] = vals

        # Lightweight null + row probes (bounded).
        probe_sql = (
            f"SELECT "
            f"COUNT(*) AS row_probe, "
            f"SUM(CASE WHEN {cq} IS NULL THEN 1 ELSE 0 END) AS null_est "
            f"FROM (SELECT {cq} FROM {tq} LIMIT 1000) AS _probe"
        )
        try:
            probe = await db_provider.execute_readonly(probe_sql, max_rows=1)
            rows = probe.get("rows") or []
            if rows:
                row0 = rows[0]
                if isinstance(row0, dict):
                    out["row_probe"] = int(row0.get("row_probe") or 0)
                    null_raw = row0.get("null_est")
                    out["null_count_estimate"] = (
                        int(null_raw) if null_raw is not None else None
                    )
        except Exception:
            # Fallback: just count limited rows.
            try:
                cnt = await db_provider.execute_readonly(
                    f"SELECT COUNT(*) AS c FROM (SELECT 1 FROM {tq} LIMIT 1000) AS _r",
                    max_rows=1,
                )
                rows = cnt.get("rows") or []
                if rows and isinstance(rows[0], dict):
                    out["row_probe"] = int(rows[0].get("c") or 0)
            except Exception as exc:
                out["error"] = str(exc)
    except Exception as exc:
        out["error"] = str(exc)
        logger.debug("explore_column failed %s.%s: %s", table, column, exc)

    return out


async def explore_for_repair(
    db_provider: Any,
    tables_columns: list[tuple[str, str]],
    settings: Any,
) -> str:
    """Format a short repair-context block from column exploration.

    Honors ``settings.column_exploration_enabled`` and
    ``settings.query_timeout_seconds`` when present.
    """
    if not tables_columns:
        return ""
    enabled = True
    if settings is not None:
        enabled = bool(getattr(settings, "column_exploration_enabled", True))
    if not enabled:
        return ""

    max_distinct = 20
    if settings is not None:
        vg = getattr(settings, "value_grounding_max_distinct", None)
        if isinstance(vg, int) and vg > 0:
            max_distinct = min(20, vg)

    timeout = 8.0
    if settings is not None:
        qt = getattr(settings, "query_timeout_seconds", None)
        if isinstance(qt, (int, float)) and qt > 0:
            timeout = min(float(qt), 15.0)

    # Cap how many columns we probe in one repair pass.
    pairs = list(tables_columns)[:6]
    lines: list[str] = ["Column exploration (repair context):"]

    async def _one(table: str, column: str) -> dict:
        try:
            return await asyncio.wait_for(
                explore_column(
                    db_provider, table, column, max_distinct=max_distinct
                ),
                timeout=timeout,
            )
        except Exception as exc:
            return {
                "table": table,
                "column": column,
                "distinct_values": [],
                "null_count_estimate": None,
                "row_probe": None,
                "error": str(exc),
            }

    results = await asyncio.gather(*[_one(t, c) for t, c in pairs])
    for info in results:
        table = info.get("table")
        column = info.get("column")
        if info.get("error") and not info.get("distinct_values"):
            lines.append(f"- {table}.{column}: error={info['error']}")
            continue
        vals = info.get("distinct_values") or []
        preview = ", ".join(repr(v) for v in vals[:8])
        null_est = info.get("null_count_estimate")
        row_probe = info.get("row_probe")
        extras: list[str] = []
        if row_probe is not None:
            extras.append(f"rows~{row_probe}")
        if null_est is not None:
            extras.append(f"nulls~{null_est}")
        suffix = f" ({', '.join(extras)})" if extras else ""
        if preview:
            lines.append(f"- {table}.{column}: [{preview}]{suffix}")
        else:
            lines.append(f"- {table}.{column}: (no values){suffix}")

    if len(lines) <= 1:
        return ""
    return "\n".join(lines)
