"""Lightweight semantic layer formatting for prompt injection."""

from __future__ import annotations

import json
from typing import Any


def parse_semantic_layer(raw: str | dict | None) -> dict[str, Any]:
    """Parse JSON text or dict into a semantic-layer structure."""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def format_semantic_layer(layer: dict[str, Any] | str | None) -> str:
    """Render semantic layer as prompt text for appending to business rules.

    Expected shape::

        {
          "metrics": [{"name": "...", "sql": "...", "description": "..."}, ...],
          "synonyms": {"nl term": "canonical", ...},
          "join_paths": ["orders.customer_id = customers.id", ...],
          "table_tiers": {"orders": "fact", "customers": "dim", ...},
          "relationships": [
            {"from_table": "...", "from_col": "...", "to_table": "...",
             "to_col": "...", "status": "proposed"|"approved"}, ...
          ],
          "learned_conventions": ["...", ...],
          "reviewed_queries": [{"question": "...", "sql": "..."}, ...],
          "repair_memory": [
            {"error_pattern": "...", "fix_hint": "...",
             "sql_before": "...", "sql_after": "..."}, ...
          ]
        }

    Returns empty string when nothing useful is present.
    """
    data = parse_semantic_layer(layer)
    if not data:
        return ""

    blocks: list[str] = []

    metrics = data.get("metrics") or []
    if isinstance(metrics, list) and metrics:
        lines = ["Metrics:"]
        for m in metrics:
            if not isinstance(m, dict):
                continue
            name = str(m.get("name") or "").strip()
            if not name:
                continue
            sql = str(m.get("sql") or "").strip()
            desc = str(m.get("description") or "").strip()
            bit = f"- {name}"
            if sql:
                bit += f" = {sql}"
            if desc:
                bit += f" ({desc})"
            lines.append(bit)
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    synonyms = data.get("synonyms") or {}
    if isinstance(synonyms, dict) and synonyms:
        lines = ["Synonyms:"]
        for src, dst in synonyms.items():
            s, d = str(src).strip(), str(dst).strip()
            if s and d:
                lines.append(f"- {s} → {d}")
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    join_paths = data.get("join_paths") or []
    if isinstance(join_paths, list) and join_paths:
        lines = ["Join paths:"]
        for path in join_paths:
            text = str(path).strip()
            if text:
                lines.append(f"- {text}")
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    relationships = data.get("relationships") or []
    if isinstance(relationships, list) and relationships:
        lines = ["Relationships:"]
        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            ft = str(rel.get("from_table") or "").strip()
            fc = str(rel.get("from_col") or "").strip()
            tt = str(rel.get("to_table") or "").strip()
            tc = str(rel.get("to_col") or "").strip()
            status = str(rel.get("status") or "").strip()
            if not (ft and fc and tt and tc):
                continue
            bit = f"- {ft}.{fc} → {tt}.{tc}"
            if status:
                bit += f" [{status}]"
            lines.append(bit)
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    table_tiers = data.get("table_tiers") or {}
    if isinstance(table_tiers, dict) and table_tiers:
        lines = ["Table tiers:"]
        for table, tier in table_tiers.items():
            t, r = str(table).strip(), str(tier).strip()
            if t and r:
                lines.append(f"- {t}: {r}")
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    conventions = data.get("learned_conventions") or []
    if isinstance(conventions, list) and conventions:
        lines = ["Learned conventions:"]
        for item in conventions:
            text = str(item).strip()
            if text:
                lines.append(f"- {text}")
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    reviewed = data.get("reviewed_queries") or []
    if isinstance(reviewed, list) and reviewed:
        lines = ["Reviewed queries:"]
        for item in reviewed:
            if not isinstance(item, dict):
                continue
            q = str(item.get("question") or "").strip()
            sql = str(item.get("sql") or "").strip()
            if not q and not sql:
                continue
            if q and sql:
                lines.append(f"- Q: {q} → SQL: {sql}")
            elif q:
                lines.append(f"- Q: {q}")
            else:
                lines.append(f"- SQL: {sql}")
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    repairs = data.get("repair_memory") or []
    if isinstance(repairs, list) and repairs:
        lines = ["Repair memory:"]
        for item in repairs:
            if not isinstance(item, dict):
                continue
            pattern = str(item.get("error_pattern") or "").strip()
            hint = str(item.get("fix_hint") or "").strip()
            before = str(item.get("sql_before") or "").strip()
            after = str(item.get("sql_after") or "").strip()
            if not (pattern or hint or before or after):
                continue
            parts: list[str] = []
            if pattern:
                parts.append(f"error={pattern}")
            if hint:
                parts.append(f"hint={hint}")
            if before and after:
                parts.append(f"fix: {before} → {after}")
            elif after:
                parts.append(f"sql_after={after}")
            lines.append("- " + "; ".join(parts))
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    if not blocks:
        return ""
    return "━━━ SEMANTIC LAYER ━━━\n" + "\n\n".join(blocks)


def append_semantic_to_rules(
    business_rules: str,
    semantic_layer_json: str | None,
) -> str:
    """Append formatted semantic layer under business rules text."""
    formatted = format_semantic_layer(semantic_layer_json)
    if not formatted:
        return business_rules or "(none)"
    base = (business_rules or "").strip()
    if not base or base == "(none)":
        return formatted
    return f"{base}\n\n{formatted}"
