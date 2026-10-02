"""BIRD Mini-Dev / Dev loaders for enterprise-style stress evals.

BIRD annotation quality is uneven (see VLDB 2025 annotation-error study).
Treat scores as relative metrics only.

Layout (after ``scripts/fetch_benchmarks.py bird``):

  eval/benchmarks/data/bird/
    mini_dev_sqlite.json          # or mini_dev JSON
    dev_databases/                # 11 SQLite DBs from BIRD dev
      <db_id>/<db_id>.sqlite
    database_description/         # optional column meaning CSVs
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

_BACKEND = Path(__file__).resolve().parents[2]
DATA_DIR = _BACKEND / "eval" / "benchmarks" / "data" / "bird"


def bird_root() -> Path:
    return DATA_DIR


def bird_available() -> bool:
    root = bird_root()
    has_json = any(
        (root / name).exists()
        for name in (
            "mini_dev_sqlite.json",
            "mini_dev.json",
            "dev.json",
        )
    )
    if not has_json:
        nested = root / "mini_dev_sqlite"
        has_json = any(
            (nested / name).exists()
            for name in ("mini_dev_sqlite.json", "dev.json")
        )
    return has_json


def _find_json(root: Path) -> Path:
    for base in (root, root / "mini_dev_sqlite"):
        for name in ("mini_dev_sqlite.json", "mini_dev.json", "dev.json"):
            path = base / name
            if path.exists():
                return path
    raise FileNotFoundError(
        f"BIRD Mini-Dev JSON not found under {root}. "
        "Run: uv run python scripts/fetch_benchmarks.py bird"
    )


def load_bird_mini_dev(root: Path | None = None) -> list[dict[str, Any]]:
    base = root or bird_root()
    path = _find_json(base)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        # Some dumps wrap under a key.
        for key in ("data", "questions", "dev"):
            if isinstance(data.get(key), list):
                return list(data[key])
        raise ValueError(f"Unexpected BIRD JSON shape in {path}")
    if not isinstance(data, list):
        raise ValueError(f"Unexpected BIRD JSON shape in {path}")
    return data


def bird_db_path(db_id: str, root: Path | None = None) -> Path:
    base = root or bird_root()
    candidates = [
        base / "dev_databases" / db_id / f"{db_id}.sqlite",
        base / "dev_databases" / db_id / f"{db_id}.sqlite3",
        base / "database" / db_id / f"{db_id}.sqlite",
        base / "databases" / db_id / f"{db_id}.sqlite",
        base / db_id / f"{db_id}.sqlite",
        base / "mini_dev_sqlite" / "dev_databases" / db_id / f"{db_id}.sqlite",
    ]
    for path in candidates:
        if path.exists():
            return path
    # Fuzzy search under root.
    matches = list(base.rglob(f"{db_id}.sqlite"))
    if matches:
        return matches[0]
    raise FileNotFoundError(
        f"BIRD SQLite for {db_id!r} not found under {base}. "
        "Download BIRD dev databases via scripts/fetch_benchmarks.py"
    )


def pick_bird_stratified(
    items: list[dict[str, Any]],
    *,
    n: int = 150,
    seed: int = 42,
    per_db_cap: int | None = None,
    db_ids: list[str] | None = None,
    exclude_db_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Stratify by db_id and difficulty for a Mini-Dev subset."""
    allow = set(db_ids) if db_ids else None
    deny = set(exclude_db_ids or ())
    # Large BIRD DBs that often hang/timeout on hosted APIs during pilots.
    deny |= {"card_games", "european_football_2", "codebase_community"}
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        db = str(
            item.get("db_id")
            or item.get("db")
            or item.get("selected_database")
            or "unknown"
        )
        if allow is not None and db not in allow:
            continue
        if db in deny:
            continue
        hard = str(
            item.get("difficulty") or item.get("difficulty_tier") or "unknown"
        ).lower()
        enriched = dict(item)
        enriched["_hardness"] = hard
        enriched["db_id"] = db
        by_key[(db, hard)].append(enriched)

    rng = random.Random(seed)
    for bucket in by_key.values():
        rng.shuffle(bucket)

    keys = sorted(by_key.keys())
    picked: list[dict[str, Any]] = []
    per_db_counts: dict[str, int] = defaultdict(int)
    # Round-robin across (db, difficulty) buckets.
    while len(picked) < n:
        progress = False
        for key in keys:
            if len(picked) >= n:
                break
            db, _hard = key
            if per_db_cap is not None and per_db_counts[db] >= per_db_cap:
                continue
            bucket = by_key[key]
            if not bucket:
                continue
            picked.append(bucket.pop())
            per_db_counts[db] += 1
            progress = True
        if not progress:
            break
    return picked[:n]


def description_csv_dir(root: Path | None = None) -> Path | None:
    base = root or bird_root()
    for candidate in (
        base / "database_description",
        base / "dev_databases" / "database_description",
        base / "mini_dev_sqlite" / "database_description",
    ):
        if candidate.is_dir():
            return candidate
    # BIRD often nests per-db CSVs under each database folder.
    return None
