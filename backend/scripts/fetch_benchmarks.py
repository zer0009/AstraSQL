#!/usr/bin/env python3
"""Download benchmark packages into eval/benchmarks/data/ (gitignored).

Usage:
  uv run python scripts/fetch_benchmarks.py bird
  uv run python scripts/fetch_benchmarks.py spider
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlretrieve

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

BIRD_DIR = _BACKEND / "eval" / "benchmarks" / "data" / "bird"

BIRD_MINI_DEV_JSON = (
    "https://huggingface.co/datasets/birdsql/bird_mini_dev/resolve/main/"
    "data/mini_dev_sqlite-00000-of-00001.json"
)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url}")
    print(f"  -> {dest}")
    urlretrieve(url, dest)


def fetch_spider() -> None:
    from src.eval.spider_data import ensure_spider_data

    root = ensure_spider_data(force=False)
    print(f"Spider ready at {root}")


def _fetch_bird_via_hf_hub() -> bool:
    """Prefer huggingface_hub snapshot when installed."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        return False
    print("Fetching BIRD complete-devset via huggingface_hub…")
    snapshot_download(
        repo_id="EuricoGVP/birdsql_complete_devset",
        repo_type="dataset",
        local_dir=str(BIRD_DIR / "_hf_complete"),
        local_dir_use_symlinks=False,
    )
    # Normalize layouts.
    hf_root = BIRD_DIR / "_hf_complete"
    dbs_src = hf_root / "databases"
    dbs_dst = BIRD_DIR / "dev_databases"
    if dbs_src.is_dir():
        if dbs_dst.exists():
            shutil.rmtree(dbs_dst)
        shutil.copytree(dbs_src, dbs_dst)
    return dbs_dst.is_dir() and any(dbs_dst.rglob("*.sqlite"))


def fetch_bird(*, force: bool = False) -> None:
    print(
        "\n=== BIRD license notice ===\n"
        "BIRD (BIg Bench for LaRge-scale Database Grounded Text-to-SQL)\n"
        "is released for research. See https://bird-bench.github.io/\n"
        "and the dataset cards on Hugging Face (birdsql/*).\n"
        "Scores are relative; annotation quality varies.\n"
    )
    BIRD_DIR.mkdir(parents=True, exist_ok=True)

    json_dest = BIRD_DIR / "mini_dev_sqlite.json"
    if force or not json_dest.exists():
        try:
            _download(BIRD_MINI_DEV_JSON, json_dest)
            data = json.loads(json_dest.read_text(encoding="utf-8"))
            # HF datasets sometimes wrap rows.
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
                json_dest.write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8"
                )
            n = len(data) if isinstance(data, list) else "?"
            print(f"  Mini-Dev JSON: {n} items")
        except Exception as exc:
            print(f"WARNING: Mini-Dev JSON download failed: {exc}")
            if json_dest.exists():
                json_dest.unlink()

    dbs_marker = BIRD_DIR / "dev_databases"
    have_dbs = dbs_marker.is_dir() and any(dbs_marker.rglob("*.sqlite"))
    if force or not have_dbs:
        ok = False
        try:
            ok = _fetch_bird_via_hf_hub()
        except Exception as exc:
            print(f"huggingface_hub fetch failed: {exc}")
        if not ok:
            # Fallback: try a few known zip mirrors (may 404).
            for url in (
                "https://huggingface.co/datasets/EuricoGVP/birdsql_complete_devset/"
                "resolve/main/databases.zip",
            ):
                zip_path = BIRD_DIR / "databases.zip"
                try:
                    _download(url, zip_path)
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        zf.extractall(BIRD_DIR)
                    ok = True
                    break
                except HTTPError as exc:
                    print(f"  skip {url}: {exc}")
                except Exception as exc:
                    print(f"  skip {url}: {exc}")
        if not ok:
            print(
                "WARNING: Could not download BIRD databases.\n"
                "Place the 11 BIRD-dev .sqlite files under:\n"
                f"  {BIRD_DIR / 'dev_databases' / '<db_id>' / '<db_id>.sqlite'}\n"
                "Or: pip/uv add huggingface_hub && re-run this script."
            )

    print(f"BIRD data root: {BIRD_DIR}")
    if json_dest.exists():
        try:
            n = len(json.loads(json_dest.read_text(encoding="utf-8")))
            print(f"  questions JSON: {json_dest} ({n} items)")
        except Exception:
            print(f"  questions JSON present: {json_dest}")
    sqlite_count = len(list(BIRD_DIR.rglob("*.sqlite")))
    print(f"  sqlite files found: {sqlite_count}")


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch AstraSQL eval benchmarks")
    p.add_argument("dataset", choices=["bird", "spider", "all"])
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    if args.dataset in {"spider", "all"}:
        fetch_spider()
    if args.dataset in {"bird", "all"}:
        fetch_bird(force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
