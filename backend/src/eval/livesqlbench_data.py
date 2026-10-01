"""LiveSQLBench loader + HKB → semantic-layer helpers.

Expected layout (set ``LIVESQLBENCH_ROOT`` or pass ``root``)::

  eval/benchmarks/data/livesqlbench/
    tasks.json          # or *.json task list
    kb.jsonl            # optional hierarchical knowledge base lines

Task items typically include question / SQL / db_id fields.
HKB (``kb.jsonl``) lines are converted into metrics/synonyms text for
``semantic_layer_json`` injection during eval.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
DATA_DIR = _BACKEND / "eval" / "benchmarks" / "data" / "livesqlbench"


def livesqlbench_root() -> Path:
    env = (os.environ.get("LIVESQLBENCH_ROOT") or "").strip()
    return Path(env) if env else DATA_DIR


def livesqlbench_available(root: Path | None = None) -> bool:
    base = root or livesqlbench_root()
    if not base.is_dir():
        return False
    return any(base.glob("*.json")) or (base / "kb.jsonl").exists()


def load_livesqlbench_tasks(root: Path | None = None) -> list[dict[str, Any]]:
    """Load LiveSQLBench task JSON list."""
    base = root or livesqlbench_root()
    candidates = []
    for name in ("tasks.json", "dev.json", "test.json"):
        p = base / name
        if p.exists():
            candidates.append(p)
    if not candidates and base.is_dir():
        candidates = sorted(base.glob("*.json"))
    if not candidates:
        raise FileNotFoundError(
            f"LiveSQLBench tasks not found under {base}. "
            "Set LIVESQLBENCH_ROOT or place tasks.json there."
        )
    for path in candidates:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("tasks", "examples", "data", "items"):
                if isinstance(data.get(key), list):
                    return list(data[key])
    raise FileNotFoundError(f"No task list in {base}")


def load_kb_jsonl(path: Path | str | None = None, root: Path | None = None) -> list[dict[str, Any]]:
    """Load optional kb.jsonl (one JSON object per line)."""
    if path is not None:
        p = Path(path)
    else:
        p = (root or livesqlbench_root()) / "kb.jsonl"
    if not p.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            entries.append(obj)
    return entries


def hkb_to_semantic_layer_text(entries: list[dict[str, Any]]) -> str:
    """Convert HKB entries into metrics/synonyms-style prompt text."""
    metrics: list[str] = []
    synonyms: list[str] = []
    other: list[str] = []

    for e in entries:
        kind = str(e.get("type") or e.get("kind") or e.get("category") or "").lower()
        name = str(e.get("name") or e.get("term") or e.get("metric") or "").strip()
        content = str(
            e.get("definition")
            or e.get("description")
            or e.get("text")
            or e.get("content")
            or ""
        ).strip()
        sql = str(e.get("sql") or e.get("formula") or "").strip()
        alias = str(e.get("synonym") or e.get("alias") or e.get("canonical") or "").strip()

        if kind in ("metric", "measure", "kpi") or sql:
            bit = name or "metric"
            if sql:
                bit += f" = {sql}"
            if content:
                bit += f" ({content})"
            metrics.append(f"- {bit}")
        elif kind in ("synonym", "alias") or (name and alias):
            src = name or content
            dst = alias or content
            if src and dst and src != dst:
                synonyms.append(f"- {src} → {dst}")
        elif content or name:
            other.append(f"- {name or content}" + (f": {content}" if name and content else ""))

    blocks: list[str] = []
    if metrics:
        blocks.append("Metrics:\n" + "\n".join(metrics))
    if synonyms:
        blocks.append("Synonyms:\n" + "\n".join(synonyms))
    if other:
        blocks.append("Knowledge:\n" + "\n".join(other))
    if not blocks:
        return ""
    return "━━━ LIVESQLBENCH HKB ━━━\n" + "\n\n".join(blocks)


def hkb_to_semantic_layer_dict(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert HKB entries into a semantic_layer_json-compatible dict."""
    metrics: list[dict[str, Any]] = []
    synonyms: dict[str, str] = {}
    for e in entries:
        kind = str(e.get("type") or e.get("kind") or e.get("category") or "").lower()
        name = str(e.get("name") or e.get("term") or e.get("metric") or "").strip()
        content = str(
            e.get("definition")
            or e.get("description")
            or e.get("text")
            or e.get("content")
            or ""
        ).strip()
        sql = str(e.get("sql") or e.get("formula") or "").strip()
        alias = str(e.get("synonym") or e.get("alias") or e.get("canonical") or "").strip()
        if kind in ("metric", "measure", "kpi") or (name and sql):
            if name:
                metrics.append(
                    {"name": name, "sql": sql or None, "description": content or None}
                )
        elif name and alias:
            synonyms[name] = alias
        elif kind in ("synonym", "alias") and name and content:
            synonyms[name] = content
    layer: dict[str, Any] = {}
    if metrics:
        layer["metrics"] = metrics
    if synonyms:
        layer["synonyms"] = synonyms
    return layer
