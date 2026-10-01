"""TPC-H style latency probes (no data generation).

Runs fixed aggregate SQLs against an already-loaded warehouse-like SQLite/DB
provider and records ``elapsed_ms``. Point ``TPC_DB_PATH`` / pass a provider.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

# Classic TPC-H-shaped aggregates. Tables may not exist — probes record errors.
DEFAULT_PROBES: list[dict[str, str]] = [
    {
        "id": "tpch-q1-agg",
        "sql": (
            "SELECT COUNT(*) AS n, SUM(l_quantity) AS qty "
            "FROM lineitem WHERE l_shipdate <= '1998-12-01'"
        ),
    },
    {
        "id": "tpch-q3-rev",
        "sql": (
            "SELECT o_orderkey, SUM(l_extendedprice * (1 - l_discount)) AS revenue "
            "FROM customer, orders, lineitem "
            "WHERE c_mktsegment = 'BUILDING' "
            "AND c_custkey = o_custkey AND l_orderkey = o_orderkey "
            "GROUP BY o_orderkey LIMIT 20"
        ),
    },
    {
        "id": "tpch-q5-region",
        "sql": (
            "SELECT n_name, SUM(l_extendedprice * (1 - l_discount)) AS revenue "
            "FROM customer, orders, lineitem, supplier, nation, region "
            "WHERE c_custkey = o_custkey AND l_orderkey = o_orderkey "
            "AND l_suppkey = s_suppkey AND c_nationkey = s_nationkey "
            "AND s_nationkey = n_nationkey AND n_regionkey = r_regionkey "
            "GROUP BY n_name LIMIT 20"
        ),
    },
    {
        "id": "tpch-q6-revenue",
        "sql": (
            "SELECT SUM(l_extendedprice * l_discount) AS revenue "
            "FROM lineitem "
            "WHERE l_shipdate >= '1994-01-01' AND l_shipdate < '1995-01-01' "
            "AND l_discount BETWEEN 0.05 AND 0.07 AND l_quantity < 24"
        ),
    },
]


def tpc_db_path() -> Path | None:
    env = (os.environ.get("TPC_DB_PATH") or "").strip()
    return Path(env) if env else None


async def run_probe_sql(
    db_provider: Any,
    sql: str,
    *,
    max_rows: int = 50,
) -> dict[str, Any]:
    """Execute one SQL via ``execute_readonly``; return elapsed_ms + status."""
    t0 = time.perf_counter()
    error: str | None = None
    row_count: int | None = None
    try:
        result = await db_provider.execute_readonly(sql, max_rows=max_rows)
        row_count = (result or {}).get("row_count")
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "elapsed_ms": round(elapsed_ms, 3),
        "ok": error is None,
        "error": error,
        "row_count": row_count,
    }


async def run_tpc_latency_probes(
    db_provider: Any,
    probes: list[dict[str, str]] | None = None,
    *,
    max_rows: int = 50,
) -> dict[str, Any]:
    """Run fixed aggregate probes; return per-probe and summary latency stats."""
    items = probes or DEFAULT_PROBES
    results: list[dict[str, Any]] = []
    for probe in items:
        pid = str(probe.get("id") or "probe")
        sql = str(probe.get("sql") or "").strip()
        if not sql:
            continue
        outcome = await run_probe_sql(db_provider, sql, max_rows=max_rows)
        results.append({"id": pid, "sql": sql, **outcome})

    ok_ms = [r["elapsed_ms"] for r in results if r.get("ok")]
    summary = {
        "n": len(results),
        "n_ok": len(ok_ms),
        "elapsed_ms_mean": round(sum(ok_ms) / len(ok_ms), 3) if ok_ms else None,
        "elapsed_ms_max": round(max(ok_ms), 3) if ok_ms else None,
        "elapsed_ms_min": round(min(ok_ms), 3) if ok_ms else None,
    }
    return {"summary": summary, "probes": results}


def run_tpc_latency_probes_sync(
    db_provider: Any,
    probes: list[dict[str, str]] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Sync wrapper around :func:`run_tpc_latency_probes`."""
    return asyncio.run(run_tpc_latency_probes(db_provider, probes, **kwargs))
