"""Spider 2.0-lite SQLite subset loader stub for wide-schema stress evals.

Place files under:

  eval/benchmarks/data/spider2/lite/
    (follow Spider 2.0 release layout)

No automatic download. Scores are directional only — enterprise workflows
differ from Spider 1.0.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
DATA_DIR = _BACKEND / "eval" / "benchmarks" / "data" / "spider2"


def spider2_lite_root() -> Path:
    return DATA_DIR / "lite"


def spider2_available() -> bool:
    root = spider2_lite_root()
    return any(root.glob("*.json")) if root.is_dir() else False


def load_spider2_lite(root: Path | None = None) -> list[dict[str, Any]]:
    base = root or spider2_lite_root()
    candidates = sorted(base.glob("*.json")) if base.is_dir() else []
    if not candidates:
        raise FileNotFoundError(
            f"Spider 2.0-lite JSON not found under {base}. "
            "Download from spider2-sql.github.io and place files there."
        )
    # Prefer a file that looks like an examples list.
    for path in candidates:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "examples" in data:
            return list(data["examples"])
    raise FileNotFoundError(f"No example list found in {base}")
