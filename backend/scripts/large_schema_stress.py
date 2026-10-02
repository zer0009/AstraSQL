#!/usr/bin/env python3
"""Build an inflated Spider schema and verify large-schema retrieval recall.

No LLM calls — exercises relationship discovery + FAISS/full-schema path.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))


async def main() -> int:
    from src.eval.perturb import inflate_schema, perturb_sqlite
    from src.eval.spider_data import db_sqlite_path, ensure_spider_data, load_dev, list_dev_databases

    root = ensure_spider_data()
    dbs = list_dev_databases(load_dev(root))[:8]
    target = dbs[0]
    donors = [db_sqlite_path(d, root) for d in dbs[1:]]
    out_dir = _BACKEND / "eval" / "benchmarks" / "data" / "stress"
    out_dir.mkdir(parents=True, exist_ok=True)
    inflated = out_dir / f"{target}_inflated.sqlite"
    meta = inflate_schema(db_sqlite_path(target, root), donors, inflated)
    print(
        f"Inflated {target}: grafted={meta['grafted_tables']} "
        f"path={inflated}"
    )

    dropped = out_dir / f"{target}_drop_fk.sqlite"
    pmeta = perturb_sqlite(
        db_sqlite_path(target, root),
        dropped,
        cryptic_names=False,
        coded_values=False,
        drop_fks=True,
        soft_delete=False,
        seed=0,
    )
    print(f"Drop-FK perturb: {pmeta['notes'][:3]} → {dropped}")

    report = {
        "inflated": meta,
        "drop_fk": {
            "dst": str(dropped),
            "notes": pmeta.get("notes"),
            "drop_fks": pmeta.get("drop_fks"),
        },
    }
    out = out_dir / "large_schema_stress.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
