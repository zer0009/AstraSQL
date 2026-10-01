"""Discover proposed join relationships from schema metadata.

Uses structural signals only (column-name patterns, type compatibility,
optional inclusion-dependency probes). No hardcoded domain vocabularies.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from typing import Any

logger = logging.getLogger(__name__)

# Column-name suffixes that commonly denote foreign-key-like references.
_FK_SUFFIXES = ("_id", "_key", "_fk", "_code", "_uid", "id")
# Minimum score to keep a proposed edge (0–1 scale).
_MIN_SCORE = 0.45
# Score floor for auto-approve when probes are unavailable.
_AUTO_APPROVE_SCORE = 0.72
# Sample size for inclusion-dependency probes.
_PROBE_LIMIT = 20

_TYPE_INT = frozenset(
    {
        "int",
        "integer",
        "bigint",
        "smallint",
        "tinyint",
        "serial",
        "bigserial",
        "int2",
        "int4",
        "int8",
        "number",
        "numeric",
        "decimal",
    }
)
_TYPE_FLOAT = frozenset({"float", "double", "real", "float4", "float8"})
_TYPE_TEXT = frozenset(
    {
        "text",
        "varchar",
        "char",
        "character",
        "nvarchar",
        "nchar",
        "string",
        "citext",
        "uuid",
    }
)
_TYPE_DATE = frozenset(
    {"date", "datetime", "timestamp", "timestamptz", "time", "datetime2"}
)


def _norm_type(raw: str | None) -> str:
    base = (raw or "").strip().lower()
    base = re.split(r"[\s(]", base, maxsplit=1)[0]
    if base in _TYPE_INT or base.startswith("int"):
        return "int"
    if base in _TYPE_FLOAT:
        return "float"
    if base in _TYPE_TEXT or "char" in base or base.endswith("text"):
        return "text"
    if base in _TYPE_DATE or "timestamp" in base or base.startswith("date"):
        return "date"
    return base or "other"


def _types_compatible(a: str | None, b: str | None) -> bool:
    na, nb = _norm_type(a), _norm_type(b)
    if na == nb:
        return True
    if {na, nb} <= {"int", "float"}:
        return True
    # Unknown / other — allow but score lower later.
    return na == "other" or nb == "other"


def _table_name(entry: dict[str, Any]) -> str:
    return str(entry.get("table_name") or entry.get("name") or "").strip()


def _col_name(col: dict[str, Any]) -> str:
    return str(col.get("name") or col.get("column_name") or "").strip()


def _col_type(col: dict[str, Any]) -> str:
    return str(col.get("type") or col.get("data_type") or "")


def _is_pk(col: dict[str, Any]) -> bool:
    return bool(col.get("primary_key"))


def _declared_fk(col: dict[str, Any]) -> tuple[str, str] | None:
    fk = col.get("foreign_key")
    if isinstance(fk, dict):
        t = fk.get("table") or fk.get("foreign_table_name")
        c = fk.get("column") or fk.get("foreign_column_name")
        if t and c:
            return str(t), str(c)
    return None


def _plural_variants(stem: str) -> list[str]:
    """Lightweight English plural/singular variants (no domain lists)."""
    s = stem.lower()
    out: list[str] = [s]
    if s.endswith("ies") and len(s) > 3:
        out.append(s[:-3] + "y")
    elif s.endswith("ses") and len(s) > 3:
        out.append(s[:-2])
    elif s.endswith("s") and len(s) > 1:
        out.append(s[:-1])
    else:
        out.append(s + "s")
        if s.endswith("y") and len(s) > 1 and s[-2] not in "aeiou":
            out.append(s[:-1] + "ies")
    # Dedupe preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered


def _fk_stem(col_name: str) -> str | None:
    """Extract reference stem from a column name (customer_id → customer)."""
    lower = col_name.lower()
    for suffix in _FK_SUFFIXES:
        if suffix == "id":
            # Bare trailing "id" only when preceded by underscore or whole name.
            if lower == "id":
                return None
            if lower.endswith("id") and len(lower) > 2 and lower[-3] != "_":
                # e.g. userid → user (weak); require underscore form preferred.
                continue
            continue
        if lower.endswith(suffix) and len(lower) > len(suffix):
            return lower[: -len(suffix)]
    if lower.endswith("_id") and len(lower) > 3:
        return lower[:-3]
    return None


def _edge_key(ft: str, fc: str, tt: str, tc: str) -> tuple[str, str, str, str]:
    return (ft.lower(), fc.lower(), tt.lower(), tc.lower())


def _score_candidate(
    *,
    name_match: float,
    type_ok: bool,
    target_is_pk: bool,
    inclusion: float | None,
    declared: bool,
) -> float:
    if declared:
        return 1.0
    score = 0.35 * name_match
    score += 0.2 if type_ok else 0.0
    score += 0.2 if target_is_pk else 0.05
    if inclusion is not None:
        score += 0.25 * max(0.0, min(1.0, inclusion))
    else:
        # No probe — slight credit for strong name+pk signals.
        if name_match >= 0.9 and target_is_pk and type_ok:
            score += 0.15
    return round(min(1.0, score), 3)


async def _probe_inclusion(
    db_provider: Any,
    from_table: str,
    from_col: str,
    to_table: str,
    to_col: str,
) -> float | None:
    """Estimate fraction of sampled from-values that exist in the target column."""
    if db_provider is None:
        return None
    quote = getattr(db_provider, "quote_ident", None)

    def q(name: str) -> str:
        if callable(quote):
            try:
                return str(quote(name))
            except Exception:
                pass
        return f'"{name}"' if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name) else name

    try:
        sample_sql = (
            f"SELECT DISTINCT {q(from_col)} AS v FROM {q(from_table)} "
            f"WHERE {q(from_col)} IS NOT NULL "
            f"LIMIT {_PROBE_LIMIT}"
        )
        sample = await db_provider.execute_readonly(sample_sql, max_rows=_PROBE_LIMIT)
        rows = sample.get("rows") or []
        values: list[Any] = []
        for row in rows:
            if isinstance(row, dict):
                raw = row.get("v")
                if raw is None and row:
                    raw = next(iter(row.values()), None)
            else:
                raw = row
            if raw is not None:
                values.append(raw)
        if not values:
            return None

        hits = 0
        checked = 0
        for val in values[:_PROBE_LIMIT]:
            checked += 1
            # Bind-free literal for probe (numbers / short strings only).
            if isinstance(val, bool):
                lit = "1" if val else "0"
            elif isinstance(val, (int, float)):
                lit = str(val)
            else:
                text = str(val)
                if len(text) > 64 or "'" in text or "\\" in text:
                    continue
                lit = f"'{text}'"
            probe_sql = (
                f"SELECT 1 AS ok FROM {q(to_table)} "
                f"WHERE {q(to_col)} = {lit} LIMIT 1"
            )
            try:
                result = await db_provider.execute_readonly(probe_sql, max_rows=1)
                if (result.get("row_count") or 0) > 0 or (result.get("rows") or []):
                    hits += 1
            except Exception:
                continue
        if checked == 0:
            return None
        return hits / checked
    except Exception:
        logger.debug(
            "inclusion probe failed %s.%s → %s.%s",
            from_table,
            from_col,
            to_table,
            to_col,
            exc_info=True,
        )
        return None


def _explicit_fk_edges(tables_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert declared foreign keys into approved edges (score=1)."""
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for table in tables_data:
        tname = _table_name(table)
        if not tname:
            continue
        for col in table.get("columns") or []:
            if not isinstance(col, dict):
                continue
            cname = _col_name(col)
            if not cname:
                continue
            declared = _declared_fk(col)
            if declared:
                tt, tc = declared
                key = _edge_key(tname, cname, tt, tc)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    {
                        "from_table": tname,
                        "from_col": cname,
                        "to_table": tt,
                        "to_col": tc,
                        "status": "approved",
                        "score": 1.0,
                        "evidence": ["declared_fk"],
                    }
                )
        for fk in table.get("foreign_keys") or []:
            if not isinstance(fk, dict):
                continue
            cname = str(fk.get("column_name") or fk.get("column") or "").strip()
            tt = str(fk.get("foreign_table_name") or fk.get("table") or "").strip()
            tc = str(
                fk.get("foreign_column_name")
                or (fk.get("column") if "foreign_table_name" in fk else "")
                or ""
            ).strip()
            if not (cname and tt and tc):
                continue
            key = _edge_key(tname, cname, tt, tc)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "from_table": tname,
                    "from_col": cname,
                    "to_table": tt,
                    "to_col": tc,
                    "status": "approved",
                    "score": 1.0,
                    "evidence": ["declared_fk"],
                }
            )
    return edges


async def discover_relationships(
    tables_data: list[dict[str, Any]],
    db_provider: Any = None,
    *,
    auto_approve: bool = True,
    max_probes: int = 50,
) -> list[dict]:
    """Discover join edges from schema metadata (+ optional DB probes).

    Returns list of::

        {from_table, from_col, to_table, to_col, status, score, evidence}
    """
    if not tables_data:
        return []

    # Index tables / PKs / columns.
    tables_by_lower: dict[str, str] = {}
    pk_by_table: dict[str, list[tuple[str, str]]] = defaultdict(list)
    cols_by_table: dict[str, list[dict[str, Any]]] = {}

    for table in tables_data:
        tname = _table_name(table)
        if not tname:
            continue
        tables_by_lower[tname.lower()] = tname
        columns = [c for c in (table.get("columns") or []) if isinstance(c, dict)]
        cols_by_table[tname] = columns
        for col in columns:
            cname = _col_name(col)
            if cname and _is_pk(col):
                pk_by_table[tname].append((cname, _col_type(col)))
        # Fallback: column named id
        if tname not in pk_by_table or not pk_by_table[tname]:
            for col in columns:
                cname = _col_name(col)
                if cname.lower() == "id":
                    pk_by_table[tname].append((cname, _col_type(col)))
                    break

    edges = _explicit_fk_edges(tables_data)
    seen = {
        _edge_key(e["from_table"], e["from_col"], e["to_table"], e["to_col"])
        for e in edges
    }

    # Name-suffix candidates.
    candidates: list[dict[str, Any]] = []
    for from_table, columns in cols_by_table.items():
        for col in columns:
            if _declared_fk(col):
                continue
            cname = _col_name(col)
            if not cname:
                continue
            stem = _fk_stem(cname)
            if not stem:
                continue
            ctype = _col_type(col)
            for variant in _plural_variants(stem):
                to_table = tables_by_lower.get(variant)
                if not to_table or to_table == from_table:
                    continue
                pks = pk_by_table.get(to_table) or []
                # Prefer PK id, else any PK, else column matching stem.
                targets: list[tuple[str, str, bool, float]] = []
                for pk_name, pk_type in pks:
                    name_match = 1.0 if pk_name.lower() == "id" else 0.85
                    if pk_name.lower() == stem or pk_name.lower() == cname.lower():
                        name_match = 1.0
                    targets.append((pk_name, pk_type, True, name_match))
                if not targets:
                    for tcol in cols_by_table.get(to_table) or []:
                        tn = _col_name(tcol)
                        if tn.lower() in {stem, "id", cname.lower()}:
                            targets.append(
                                (tn, _col_type(tcol), _is_pk(tcol), 0.7)
                            )
                for to_col, to_type, is_pk, name_match in targets:
                    key = _edge_key(from_table, cname, to_table, to_col)
                    if key in seen:
                        continue
                    type_ok = _types_compatible(ctype, to_type)
                    candidates.append(
                        {
                            "from_table": from_table,
                            "from_col": cname,
                            "to_table": to_table,
                            "to_col": to_col,
                            "name_match": name_match,
                            "type_ok": type_ok,
                            "target_is_pk": is_pk,
                            "from_type": ctype,
                            "to_type": to_type,
                        }
                    )

    # Prefer higher name_match / pk targets; cap probes.
    candidates.sort(
        key=lambda c: (
            -float(c["name_match"]),
            0 if c["target_is_pk"] else 1,
            0 if c["type_ok"] else 1,
            c["from_table"],
            c["from_col"],
        )
    )

    probes_left = max(0, int(max_probes))
    for cand in candidates:
        key = _edge_key(
            cand["from_table"],
            cand["from_col"],
            cand["to_table"],
            cand["to_col"],
        )
        if key in seen:
            continue

        evidence = ["name_suffix"]
        if cand["type_ok"]:
            evidence.append("type_compatible")
        if cand["target_is_pk"]:
            evidence.append("target_pk")

        inclusion: float | None = None
        if db_provider is not None and probes_left > 0 and cand["type_ok"]:
            inclusion = await _probe_inclusion(
                db_provider,
                cand["from_table"],
                cand["from_col"],
                cand["to_table"],
                cand["to_col"],
            )
            probes_left -= 1
            if inclusion is not None:
                evidence.append(f"inclusion={inclusion:.2f}")

        score = _score_candidate(
            name_match=float(cand["name_match"]),
            type_ok=bool(cand["type_ok"]),
            target_is_pk=bool(cand["target_is_pk"]),
            inclusion=inclusion,
            declared=False,
        )
        if score < _MIN_SCORE:
            continue

        status = "proposed"
        if auto_approve and (
            score >= _AUTO_APPROVE_SCORE
            or (inclusion is not None and inclusion >= 0.8 and score >= 0.6)
        ):
            status = "approved"

        seen.add(key)
        edges.append(
            {
                "from_table": cand["from_table"],
                "from_col": cand["from_col"],
                "to_table": cand["to_table"],
                "to_col": cand["to_col"],
                "status": status,
                "score": score,
                "evidence": evidence,
            }
        )

    edges.sort(key=lambda e: (-float(e.get("score") or 0), e["from_table"], e["from_col"]))
    return edges


def shortest_join_path(
    edges: list[dict],
    source_tables: list[str] | set[str],
    dest_tables: list[str] | set[str],
) -> list[tuple]:
    """BFS shortest path of join edges connecting any source to any dest.

    Returns list of ``(from_table, from_col, to_table, to_col)`` along the path
    (oriented from source toward dest). Empty if already overlapping or unreachable.
    """
    sources = {str(t) for t in source_tables if t}
    dests = {str(t) for t in dest_tables if t}
    if not sources or not dests:
        return []
    if sources & dests:
        return []

    # Undirected adjacency: table → list of (neighbor, oriented_edge_tuple)
    adj: dict[str, list[tuple[str, tuple[str, str, str, str]]]] = defaultdict(list)
    for e in edges:
        if not isinstance(e, dict):
            continue
        status = str(e.get("status") or "proposed").lower()
        if status not in {"approved", "proposed"}:
            continue
        ft = str(e.get("from_table") or "")
        fc = str(e.get("from_col") or "")
        tt = str(e.get("to_table") or "")
        tc = str(e.get("to_col") or "")
        if not (ft and fc and tt and tc):
            continue
        forward = (ft, fc, tt, tc)
        reverse = (tt, tc, ft, fc)
        adj[ft].append((tt, forward))
        adj[tt].append((ft, reverse))

    # Multi-source BFS
    queue: deque[str] = deque()
    parent: dict[str, tuple[str, tuple[str, str, str, str]] | None] = {}
    for s in sources:
        if s in adj or s in dests:
            parent[s] = None
            queue.append(s)

    found: str | None = None
    while queue:
        node = queue.popleft()
        if node in dests and node not in sources:
            found = node
            break
        for neighbor, edge in adj.get(node, []):
            if neighbor in parent:
                continue
            parent[neighbor] = (node, edge)
            queue.append(neighbor)
            if neighbor in dests:
                found = neighbor
                queue.clear()
                break

    if found is None:
        return []

    path_edges: list[tuple] = []
    cur = found
    while cur not in sources:
        info = parent.get(cur)
        if info is None:
            return []
        prev, edge = info
        path_edges.append(edge)
        cur = prev
    path_edges.reverse()
    return path_edges


def edges_to_semantic_join_paths(edges: list[dict]) -> list[str]:
    """Format relationship edges as semantic-layer join_paths strings."""
    paths: list[str] = []
    seen: set[str] = set()
    for e in edges:
        if not isinstance(e, dict):
            continue
        status = str(e.get("status") or "").lower()
        if status and status not in {"approved", "proposed"}:
            continue
        ft = str(e.get("from_table") or "").strip()
        fc = str(e.get("from_col") or "").strip()
        tt = str(e.get("to_table") or "").strip()
        tc = str(e.get("to_col") or "").strip()
        if not (ft and fc and tt and tc):
            continue
        text = f"{ft}.{fc} = {tt}.{tc}"
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        paths.append(text)
    return paths


def merge_relationship_edges(
    existing: list[dict] | None,
    discovered: list[dict],
) -> list[dict]:
    """Merge discovered edges into an existing relationships list.

    Keeps human-approved edges; upgrades proposed→approved when rediscovered
    as approved; appends new edges.
    """
    by_key: dict[tuple[str, str, str, str], dict] = {}
    for e in existing or []:
        if not isinstance(e, dict):
            continue
        key = _edge_key(
            str(e.get("from_table") or ""),
            str(e.get("from_col") or ""),
            str(e.get("to_table") or ""),
            str(e.get("to_col") or ""),
        )
        if key[0] and key[2]:
            by_key[key] = dict(e)

    for e in discovered:
        if not isinstance(e, dict):
            continue
        key = _edge_key(
            str(e.get("from_table") or ""),
            str(e.get("from_col") or ""),
            str(e.get("to_table") or ""),
            str(e.get("to_col") or ""),
        )
        if not (key[0] and key[2]):
            continue
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = dict(e)
            continue
        # Preserve explicit approved status; otherwise take higher score / new status.
        prev_status = str(prev.get("status") or "proposed").lower()
        new_status = str(e.get("status") or "proposed").lower()
        if prev_status == "approved" and new_status != "approved":
            # Keep approved; refresh score/evidence if stronger.
            if float(e.get("score") or 0) > float(prev.get("score") or 0):
                prev["score"] = e.get("score")
                prev["evidence"] = e.get("evidence") or prev.get("evidence")
            continue
        by_key[key] = dict(e)

    return list(by_key.values())
