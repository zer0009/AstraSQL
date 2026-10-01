"""BIRD Mini-Dev loader stub for enterprise-style stress evals.

BIRD annotation quality is uneven (see VLDB 2025 annotation-error study).
Treat scores as relative metrics only. Place files under:

  eval/benchmarks/data/bird/mini_dev_sqlite/
    mini_dev_sqlite.json
    (sqlite databases as referenced by the JSON)

No automatic download — follow BIRD's license and hosting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
DATA_DIR = _BACKEND / "eval" / "benchmarks" / "data" / "bird"


def bird_root() -> Path:
    return DATA_DIR / "mini_dev_sqlite"


def bird_available() -> bool:
    root = bird_root()
    return (root / "mini_dev_sqlite.json").exists() or (root / "dev.json").exists()


def load_bird_mini_dev(root: Path | None = None) -> list[dict[str, Any]]:
    base = root or bird_root()
    for name in ("mini_dev_sqlite.json", "dev.json"):
        path = base / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"BIRD Mini-Dev JSON not found under {base}. "
        "Download manually (license-aware) and place mini_dev_sqlite.json there."
    )
