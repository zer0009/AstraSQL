"""Domain-agnostic helpers for preferring human-readable labels over raw IDs.

No business vocabulary (no Odoo/product names). Relies only on:
- FK metadata on columns
- Generic label-like column names (name, title, label, code, …)
"""

from __future__ import annotations

import re
from typing import Any

# Columns that typically hold a human-facing label on a lookup/reference table.
LABEL_COLUMN_NAMES = frozenset(
    {
        "name",
        "title",
        "label",
        "code",
        "display_name",
        "displayname",
    }
)

# Broader set kept when thinning huge schemas for prompts.
NAME_LIKE_COLUMNS = frozenset(
    {
        *LABEL_COLUMN_NAMES,
        "description",
        "fullname",
        "slug",
    }
)

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def is_label_column_name(name: str | None) -> bool:
    text = (name or "").strip().lower()
    if not text:
        return False
    if text in LABEL_COLUMN_NAMES:
        return True
    return text.endswith("_name") or text.endswith("_code") or text.endswith("_title")


def label_column_names(columns: list[dict[str, Any]] | None) -> list[str]:
    """Return preferred label column names present on a table (stable order)."""
    found: list[str] = []
    seen: set[str] = set()
    for col in columns or []:
        if not isinstance(col, dict):
            continue
        raw = col.get("name") or col.get("column_name")
        if not raw:
            continue
        name = str(raw)
        key = name.lower()
        if key in seen or not is_label_column_name(name):
            continue
        seen.add(key)
        found.append(name)
    # Prefer canonical names first.
    found.sort(
        key=lambda n: (
            0
            if n.lower() in LABEL_COLUMN_NAMES
            else 1
            if n.lower().endswith("_name")
            else 2
        )
    )
    return found


def is_fk_like_identifier(name: str | None) -> bool:
    """True when an identifier looks like a raw foreign/primary key id."""
    text = (name or "").strip().lower()
    if not text:
        return False
    if text == "id":
        return True
    return text.endswith("_id") or text.endswith("_pk") or text.endswith("_fk")


_SQL_KEYWORDS = frozenset(
    {
        "coalesce",
        "nullif",
        "null",
        "true",
        "false",
        "case",
        "when",
        "then",
        "else",
        "end",
        "cast",
        "as",
        "and",
        "or",
        "not",
        "in",
        "is",
        "like",
        "between",
        "distinct",
        "date_trunc",
        "to_char",
        "sum",
        "count",
        "avg",
        "min",
        "max",
    }
)


def _strip_id_suffix(text: str) -> str:
    lower = text.lower()
    if lower.endswith("_id"):
        return text[:-3]
    if lower.endswith("_pk") or lower.endswith("_fk"):
        return text[:-3]
    return text


def humanize_dimension_expr(expr: str) -> str:
    """Turn ``rp.country_id`` / ``COALESCE(rc.code, …)`` into a short label."""
    text = " ".join((expr or "").split()).strip().strip('"')
    if not text:
        return text

    # Complex expressions: pick the most meaningful identifier (not SQL keywords).
    # Avoid ``rsplit('.', 1)`` which breaks on ``COALESCE(rc.code, '')``.
    idents = [
        i
        for i in _IDENT_RE.findall(text)
        if i.lower() not in _SQL_KEYWORDS and not i.isdigit()
    ]
    if len(idents) >= 1 and (
        "(" in text or "->>" in text or "->" in text or "," in text
    ):
        preferred_tails = (
            "name",
            "code",
            "title",
            "label",
            "country",
            "state",
            "month",
            "date",
        )
        chosen = idents[-1]
        for pref in preferred_tails:
            for ident in reversed(idents):
                low = ident.lower()
                if low == pref or low.endswith("_" + pref):
                    chosen = ident
                    break
            else:
                continue
            break
        text = chosen
    else:
        for marker in ("->>", "->"):
            if marker in text:
                text = text.split(marker, 1)[0].strip()
                break
        if "." in text:
            text = text.rsplit(".", 1)[-1]
        text = text.strip().strip('"')

    text = _strip_id_suffix(text)
    text = text.replace("_", " ").strip()
    return text or expr


def reading_label_for_group_keys(keys: list[str] | tuple[str, ...]) -> str:
    """Build a clickable clarification label for a GROUP BY key set."""
    if not keys:
        return "No grouping (detail rows)"
    parts = [humanize_dimension_expr(k) for k in keys[:4]]
    parts = [p for p in parts if p]
    # Deduplicate while preserving order (code + name from same dimension).
    seen: set[str] = set()
    uniq: list[str] = []
    for p in parts:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    joined = ", ".join(uniq) if uniq else "dimensions"
    # If keys look like raw IDs, nudge the next turn toward readable names.
    if any(is_fk_like_identifier(_last_ident(k)) for k in keys):
        return f"Group by {joined} (show names, not ids)"
    return f"Group by {joined}"


def _last_ident(expr: str) -> str:
    text = " ".join((expr or "").split())
    for marker in ("->>", "->"):
        if marker in text:
            text = text.split(marker, 1)[0]
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    match = _IDENT_RE.findall(text.strip().strip('"'))
    return match[-1] if match else text


_FK_DECL_RE = re.compile(
    r"FOREIGN\s+KEY\s*\(\s*([A-Za-z_][\w]*)\s*\)\s*REFERENCES\s+"
    r"([A-Za-z_][\w]*)\s*\(\s*([A-Za-z_][\w]*)\s*\)",
    re.IGNORECASE,
)
_TABLE_HEADER_RE = re.compile(r"^--\s*TABLE:\s*(\S+)", re.IGNORECASE)
_COL_LINE_RE = re.compile(
    r"^\s+([A-Za-z_][\w]*)\s+[A-Za-z]",
    re.IGNORECASE,
)


def parse_schema_label_index(
    enriched_schema: str,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Parse enriched CREATE TABLE text into FK map and per-table label cols.

    Returns:
      fk_targets: ``source_column_lower → target_table``
      labels_by_table: ``table_lower → [label_column, ...]``
    """
    fk_targets: dict[str, str] = {}
    labels_by_table: dict[str, list[str]] = {}
    current: str | None = None
    for line in (enriched_schema or "").splitlines():
        header = _TABLE_HEADER_RE.match(line.strip())
        if header:
            current = header.group(1).lower()
            labels_by_table.setdefault(current, [])
            continue
        fk = _FK_DECL_RE.search(line)
        if fk:
            src_col, tgt_table, _tgt_col = fk.group(1), fk.group(2), fk.group(3)
            fk_targets[src_col.lower()] = tgt_table.lower()
            continue
        if not current:
            continue
        col_match = _COL_LINE_RE.match(line)
        if not col_match:
            continue
        col_name = col_match.group(1)
        if is_label_column_name(col_name):
            bucket = labels_by_table.setdefault(current, [])
            if col_name not in bucket:
                bucket.append(col_name)
    return fk_targets, labels_by_table


def unreadable_fk_dimension_issues(
    sql: str,
    *,
    dialect: str,
    enriched_schema: str,
) -> list[str]:
    """Flag SELECT/GROUP BY of raw FK ids when a label column is available.

    Domain-agnostic: uses only FK declarations + label-like column names in the
    enriched schema text. Returns empty when schema/SQL cannot be parsed.
    """
    import sqlglot
    from sqlglot import exp

    text = (sql or "").strip()
    if not text or not (enriched_schema or "").strip():
        return []
    fk_targets, labels_by_table = parse_schema_label_index(enriched_schema)
    if not fk_targets:
        return []
    try:
        tree = sqlglot.parse_one(text, dialect=dialect)
    except Exception:
        return []

    joined_tables: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = (table.name or "").strip().lower()
        if name:
            joined_tables.add(name)

    projected: set[str] = set()
    for col in tree.find_all(exp.Column):
        cname = (col.name or "").strip().lower()
        if cname:
            projected.add(cname)

    # Columns that drive the grain of the answer (GROUP BY keys, else SELECT dims).
    focus_cols: list[str] = []
    group = tree.find(exp.Group)
    if group is not None:
        for node in group.find_all(exp.Column):
            cname = (node.name or "").strip().lower()
            if cname:
                focus_cols.append(cname)
    if not focus_cols:
        for select_expr in getattr(tree, "selects", []) or []:
            for node in select_expr.find_all(exp.Column):
                cname = (node.name or "").strip().lower()
                if cname and cname != "*":
                    focus_cols.append(cname)

    issues: list[str] = []
    seen: set[str] = set()
    for cname in focus_cols:
        if cname in seen:
            continue
        seen.add(cname)
        target = fk_targets.get(cname)
        if not target and is_fk_like_identifier(cname) and cname.endswith("_id"):
            # Heuristic when FK decl missing from the sliced schema text.
            guess = cname[:-3]
            # Only flag when some joined/lookup table exposes labels and the
            # projected set has no label columns at all for this grain.
            target = None
            for table, labels in labels_by_table.items():
                if not labels:
                    continue
                if guess and (guess in table or table.endswith(guess)):
                    target = table
                    break
        if not target:
            continue
        labels = labels_by_table.get(target) or []
        if not labels:
            continue
        label_projected = any(lbl.lower() in projected for lbl in labels)
        if label_projected:
            continue
        issues.append(
            f"Unreadable dimension: SELECT/GROUP BY uses raw '{cname}' but "
            f"table '{target}' has label column(s) {labels[:3]}; JOIN {target} "
            f"and project the label instead of the id"
        )
    return issues


def fk_label_hint(
    foreign_key: dict[str, Any] | None,
    *,
    target_columns: list[dict[str, Any]] | None,
) -> str:
    """Schema comment fragment: FK target + preferred label columns if any."""
    if not foreign_key:
        return ""
    table = foreign_key.get("table") or foreign_key.get("foreign_table_name")
    column = foreign_key.get("column") or foreign_key.get("foreign_column_name")
    if not table:
        return ""
    base = f"FK to {table}.{column}" if column else f"FK to {table}"
    labels = label_column_names(target_columns)
    if not labels:
        return base
    shown = ", ".join(labels[:3])
    return (
        f"{base}; prefer JOIN {table} and SELECT {shown} "
        f"(not the raw id) for human-readable results"
    )
