"""Download and load Spider benchmark files for the pilot."""

from __future__ import annotations

import hashlib
import json
import random
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.request import urlretrieve

_BACKEND = Path(__file__).resolve().parents[2]
DATA_DIR = _BACKEND / "eval" / "benchmarks" / "data" / "spider"

# HAL-9001/spider-databases re-host of the Yale Spider package.
SPIDER_ZIP_URL = (
    "https://huggingface.co/datasets/HAL-9001/spider-databases/"
    "resolve/main/spider_data.zip"
)
SPIDER_ZIP_SHA256 = (
    "00636695dabed6b5f4b8328a16b13e069a2f16591d5efcce57660669c85b121b"
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_spider_data(*, force: bool = False) -> Path:
    """Download and extract Spider if needed. Returns the spider_data root."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    root = DATA_DIR / "spider_data"
    marker = root / "dev.json"
    if marker.exists() and not force:
        return root

    zip_path = DATA_DIR / "spider_data.zip"
    if force or not zip_path.exists() or _sha256(zip_path) != SPIDER_ZIP_SHA256:
        print(f"Downloading Spider package to {zip_path} …")
        urlretrieve(SPIDER_ZIP_URL, zip_path)
        digest = _sha256(zip_path)
        if digest != SPIDER_ZIP_SHA256:
            raise RuntimeError(
                f"Spider zip checksum mismatch: got {digest}, "
                f"expected {SPIDER_ZIP_SHA256}"
            )

    print(f"Extracting {zip_path} …")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(DATA_DIR)

    # Archive layout: spider_data/dev.json or top-level dev.json
    if not marker.exists():
        # Try common alternate layouts.
        for candidate in DATA_DIR.rglob("dev.json"):
            # Prefer a directory that also has database/
            parent = candidate.parent
            if (parent / "database").is_dir() or (parent / "databases").is_dir():
                return parent
        raise FileNotFoundError(
            f"dev.json not found after extracting Spider under {DATA_DIR}"
        )
    return root


def load_dev(root: Path | None = None) -> list[dict[str, Any]]:
    base = root or ensure_spider_data()
    path = base / "dev.json"
    return json.loads(path.read_text(encoding="utf-8"))


def db_sqlite_path(db_id: str, root: Path | None = None) -> Path:
    base = root or ensure_spider_data()
    candidates = [
        base / "database" / db_id / f"{db_id}.sqlite",
        base / "databases" / db_id / f"{db_id}.sqlite",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        f"SQLite file for {db_id!r} not found under {base}"
    )


def infer_hardness(sql: str) -> str:
    """Approximate Spider hardness from SQL structure (no official labels needed)."""
    text = (sql or "").lower()
    nested = text.count("select") > 1
    joins = text.count(" join ")
    group = " group by " in text
    agg = any(
        fn in text
        for fn in (" count(", " sum(", " avg(", " min(", " max(")
    )
    if nested and (joins >= 2 or (joins >= 1 and group)):
        return "extra"
    if nested or joins >= 2:
        return "hard"
    if joins == 1 or group or agg:
        return "medium"
    return "easy"


def pick_stratified(
    items: list[dict[str, Any]],
    *,
    db_id: str,
    n: int = 5,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Pick up to n questions from one database, stratified by hardness."""
    scoped = [x for x in items if x.get("db_id") == db_id]
    if not scoped:
        raise ValueError(f"No Spider questions for db_id={db_id!r}")

    by_hard: dict[str, list[dict[str, Any]]] = {
        "easy": [],
        "medium": [],
        "hard": [],
        "extra": [],
    }
    for item in scoped:
        hard = str(item.get("hardness") or infer_hardness(str(item.get("query") or "")))
        if hard not in by_hard:
            hard = "medium"
        enriched = dict(item)
        enriched["_hardness"] = hard
        by_hard[hard].append(enriched)

    rng = random.Random(seed)
    for bucket in by_hard.values():
        rng.shuffle(bucket)

    # Prefer one of each hardness, then fill with medium / easy.
    order = ["easy", "medium", "hard", "extra", "medium", "easy", "hard", "extra"]
    picked: list[dict[str, Any]] = []
    used: set[int] = set()
    for hard in order:
        if len(picked) >= n:
            break
        for item in by_hard[hard]:
            key = id(item)
            if key in used:
                continue
            used.add(key)
            picked.append(item)
            break

    if len(picked) < n:
        for item in scoped:
            enriched = dict(item)
            enriched["_hardness"] = infer_hardness(str(item.get("query") or ""))
            if id(enriched) in used or any(
                p.get("question") == enriched.get("question") for p in picked
            ):
                continue
            picked.append(enriched)
            if len(picked) >= n:
                break
    return picked[:n]


def default_pilot_db(items: list[dict[str, Any]]) -> str:
    """Prefer concert_singer when present; else the db with the most questions."""
    counts: dict[str, int] = {}
    for item in items:
        db = str(item.get("db_id") or "")
        if db:
            counts[db] = counts.get(db, 0) + 1
    if "concert_singer" in counts:
        return "concert_singer"
    if not counts:
        raise ValueError("Spider dev.json has no db_id values")
    return max(counts, key=counts.get)  # type: ignore[arg-type]


def _table_count_for_db(db_id: str, root: Path | None = None) -> int:
    """Count user tables in a Spider SQLite file (for 'small DB' ranking)."""
    import sqlite3

    path = db_sqlite_path(db_id, root)
    conn = sqlite3.connect(str(path))
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def list_dev_databases(items: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for item in items:
        db = str(item.get("db_id") or "")
        if db:
            counts[db] = counts.get(db, 0) + 1
    return sorted(counts, key=lambda d: (-counts[d], d))


def pick_small_databases(
    items: list[dict[str, Any]],
    *,
    n_dbs: int = 5,
    min_questions: int = 5,
    seed: int = 42,
    root: Path | None = None,
) -> list[str]:
    """Pick n_dbs small Spider databases that have enough questions."""
    counts: dict[str, int] = {}
    for item in items:
        db = str(item.get("db_id") or "")
        if db:
            counts[db] = counts.get(db, 0) + 1

    candidates: list[tuple[int, int, str]] = []
    for db_id, n_q in counts.items():
        if n_q < min_questions:
            continue
        try:
            n_tables = _table_count_for_db(db_id, root)
        except FileNotFoundError:
            continue
        candidates.append((n_tables, -n_q, db_id))

    if not candidates:
        raise ValueError("No Spider databases with enough questions and a SQLite file")

    # Prefer fewer tables, then more questions; shuffle ties with seed.
    rng = random.Random(seed)
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))
    # Take a pool of the smallest, then sample for diversity.
    pool = candidates[: max(n_dbs * 3, n_dbs)]
    rng.shuffle(pool)
    chosen = [db for _, _, db in pool[:n_dbs]]
    if len(chosen) < n_dbs:
        for _, _, db in candidates:
            if db not in chosen:
                chosen.append(db)
            if len(chosen) >= n_dbs:
                break
    return chosen[:n_dbs]


def pick_multi_db(
    items: list[dict[str, Any]],
    *,
    db_ids: list[str] | None = None,
    n_dbs: int = 5,
    per_db: int = 5,
    seed: int = 42,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Pick ``per_db`` stratified questions from each of ``n_dbs`` databases."""
    if db_ids is None:
        db_ids = pick_small_databases(
            items, n_dbs=n_dbs, min_questions=per_db, seed=seed, root=root
        )
    picked: list[dict[str, Any]] = []
    for i, db_id in enumerate(db_ids):
        sample = pick_stratified(
            items, db_id=db_id, n=per_db, seed=seed + i
        )
        for item in sample:
            enriched = dict(item)
            enriched["_sample_db"] = db_id
            picked.append(enriched)
    return picked


def question_stable_id(item: dict[str, Any]) -> str:
    """Stable id for a Spider item (db + question hash)."""
    db = str(item.get("db_id") or "")
    q = str(item.get("question") or "")
    digest = hashlib.sha1(f"{db}::{q}".encode()).hexdigest()[:12]
    return f"{db}:{digest}"


# Databases used in run25/run50/run100 (seed 42 small-DB pick). Tune only on these.
TUNING_DB_IDS: tuple[str, ...] = (
    "car_1",
    "concert_singer",
    "cre_Doc_Template_Mgt",
    "dog_kennels",
    "employee_hire_evaluation",
    "museum_visit",
    "network_1",
    "orchestra",
    "tvshow",
    "wta_1",
)


def pick_held_out(
    items: list[dict[str, Any]],
    *,
    n_dbs: int = 5,
    per_db: int = 12,
    seed: int = 99,
    root: Path | None = None,
    exclude_db_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Pick a held-out multi-DB sample that avoids the tuning databases.

    Uses a different default seed than the historical pilots (42) so question
    selection does not overlap the run25/50/100 question sets even if a DB
    is reused later.
    """
    excluded = set(exclude_db_ids or TUNING_DB_IDS)
    # Prefer DBs not in the tuning set; fall back to any unused combo.
    eligible = [
        db
        for db in list_dev_databases(items)
        if db not in excluded
    ]
    if not eligible:
        # Extreme fallback: any DB with enough questions, still with held-out seed.
        eligible = list_dev_databases(items)
    # Restrict pick_small_databases pool by filtering items.
    filtered = [x for x in items if str(x.get("db_id") or "") in set(eligible)]
    if not filtered:
        filtered = items
    db_ids = pick_small_databases(
        filtered,
        n_dbs=n_dbs,
        min_questions=per_db,
        seed=seed,
        root=root,
    )
    picked = pick_multi_db(
        items,
        db_ids=db_ids,
        per_db=per_db,
        seed=seed,
        root=root,
    )
    for item in picked:
        item["_split"] = "held_out"
    return picked


def pick_tuning_split(
    items: list[dict[str, Any]],
    *,
    n_dbs: int = 10,
    per_db: int = 6,
    seed: int = 42,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Dev/tune split on the historical small-DB set (seed 42 family)."""
    available = [db for db in TUNING_DB_IDS if any(
        str(x.get("db_id") or "") == db for x in items
    )]
    db_ids = available[:n_dbs] if available else None
    picked = pick_multi_db(
        items,
        db_ids=db_ids,
        n_dbs=n_dbs,
        per_db=per_db,
        seed=seed,
        root=root,
    )
    for item in picked:
        item["_split"] = "tune"
    return picked
