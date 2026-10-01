"""Programmatic schema perturbation for Spider/BIRD SQLite databases.

Copies a source DB then mutates the copy (stdlib ``sqlite3`` only).
Useful as a Tier-B stress step after clean Spider accuracy.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _cryptic_name(original: str, used: set[str], rng_counter: list[int]) -> str:
    """Abbreviate a column name; ensure uniqueness within the table."""
    parts = re.split(r"[_\s]+", original.strip())
    letters = "".join((p[:1] or "x") for p in parts if p)
    if not letters:
        letters = "c"
    base = f"{letters.lower()}_{rng_counter[0]}"
    rng_counter[0] += 1
    candidate = base
    n = 2
    while candidate in used:
        candidate = f"{base}_{n}"
        n += 1
    used.add(candidate)
    return candidate


def _is_categorical_text(conn: sqlite3.Connection, table: str, col: str) -> bool:
    """Heuristic: TEXT-ish column with small distinct cardinality."""
    q_table = _quote_ident(table)
    q_col = _quote_ident(col)
    try:
        cur = conn.execute(
            f"SELECT COUNT(DISTINCT {q_col}), COUNT(*) FROM {q_table}"
        )
        distinct, total = cur.fetchone()
    except sqlite3.Error:
        return False
    if total is None or total == 0 or distinct is None:
        return False
    # Cap: categorical codes for low-cardinality string columns.
    return int(distinct) <= 40 and int(distinct) <= max(2, int(total) * 0.5)


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _column_info(conn: sqlite3.Connection, table: str) -> list[tuple]:
    return list(conn.execute(f"PRAGMA table_info({_quote_ident(table)})"))


def _fk_list(conn: sqlite3.Connection, table: str) -> list[tuple]:
    return list(conn.execute(f"PRAGMA foreign_key_list({_quote_ident(table)})"))


def _sql_type(col_type: str | None) -> str:
    t = (col_type or "TEXT").strip()
    return t if t else "TEXT"


def perturb_sqlite(
    src_path: str | Path,
    dst_path: str | Path,
    *,
    cryptic_names: bool = True,
    coded_values: bool = True,
    drop_fks: bool = True,
    soft_delete: bool = True,
    seed: int = 0,
) -> dict[str, Any]:
    """Copy ``src_path`` → ``dst_path`` and apply optional perturbations.

    Returns a dict with rename maps, value code maps, and human notes.
    """
    src = Path(src_path)
    dst = Path(dst_path)
    if not src.exists():
        raise FileNotFoundError(f"Source SQLite DB not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)

    column_renames: dict[str, dict[str, str]] = {}
    value_maps: dict[str, dict[str, str]] = {}
    notes: list[str] = [f"seed={seed}"]

    conn = sqlite3.connect(str(dst))
    try:
        # Disable FK enforcement while rebuilding.
        conn.execute("PRAGMA foreign_keys=OFF")
        tables = _table_names(conn)

        for table in tables:
            cols = _column_info(conn, table)
            if not cols:
                continue

            # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
            old_names = [c[1] for c in cols]
            rename: dict[str, str] = {}
            used: set[str] = set()
            counter = [seed + 1]

            if cryptic_names:
                for name in old_names:
                    rename[name] = _cryptic_name(name, used, counter)
                column_renames[table] = dict(rename)
                notes.append(f"{table}: cryptic column renames ({len(rename)})")
            else:
                rename = {n: n for n in old_names}

            # Soft-delete column name (avoid collision with renames).
            soft_col = None
            if soft_delete:
                soft_col = "is_deleted"
                if soft_col in used or soft_col in rename.values():
                    soft_col = "soft_delete"
                used.add(soft_col)

            # Categorical value coding (on original column names before rebuild).
            text_code_maps: dict[str, dict[str, str]] = {}
            if coded_values:
                for c in cols:
                    cname, ctype = c[1], (c[2] or "")
                    if "INT" in ctype.upper() or "REAL" in ctype.upper() or "BLOB" in ctype.upper():
                        # Still allow pure TEXT / empty affinity.
                        if ctype and "CHAR" not in ctype.upper() and "TEXT" not in ctype.upper() and "CLOB" not in ctype.upper():
                            if ctype.strip():
                                continue
                    if not _is_categorical_text(conn, table, cname):
                        continue
                    distinct = [
                        r[0]
                        for r in conn.execute(
                            f"SELECT DISTINCT {_quote_ident(cname)} "
                            f"FROM {_quote_ident(table)} "
                            f"WHERE {_quote_ident(cname)} IS NOT NULL"
                        ).fetchall()
                    ]
                    mapping: dict[str, str] = {}
                    for i, val in enumerate(sorted(distinct, key=lambda v: str(v))):
                        mapping[str(val)] = f"C{i}"
                    if mapping:
                        text_code_maps[cname] = mapping
                        value_maps[f"{table}.{cname}"] = dict(mapping)
                if text_code_maps:
                    notes.append(
                        f"{table}: coded {len(text_code_maps)} categorical column(s)"
                    )

            fks = [] if drop_fks else _fk_list(conn, table)
            if drop_fks and _fk_list(conn, table):
                notes.append(f"{table}: dropped FOREIGN KEY constraints")

            # Build new CREATE TABLE.
            col_defs: list[str] = []
            for c in cols:
                _cid, name, ctype, notnull, dflt, pk = c
                new_name = rename[name]
                bits = [_quote_ident(new_name), _sql_type(ctype)]
                if pk:
                    bits.append("PRIMARY KEY")
                if notnull and not pk:
                    bits.append("NOT NULL")
                if dflt is not None:
                    bits.append(f"DEFAULT {dflt}")
                col_defs.append(" ".join(bits))

            if soft_col:
                col_defs.append(f"{_quote_ident(soft_col)} INTEGER DEFAULT 0")
                notes.append(f"{table}: added {soft_col} column")

            # FK clauses (optional).
            for fk in fks:
                # id, seq, table, from, to, on_update, on_delete, match
                src_col = rename.get(fk[3], fk[3])
                ref_table = fk[2]
                ref_col = fk[4]
                col_defs.append(
                    f"FOREIGN KEY ({_quote_ident(src_col)}) "
                    f"REFERENCES {_quote_ident(ref_table)}({_quote_ident(ref_col)})"
                )

            tmp = f"__pert_{table}"
            # Avoid collision if tmp exists.
            while tmp in tables or tmp in _table_names(conn):
                tmp = tmp + "_x"

            create_sql = (
                f"CREATE TABLE {_quote_ident(tmp)} ({', '.join(col_defs)})"
            )
            conn.execute(create_sql)

            # Copy data with optional value coding.
            old_q = ", ".join(_quote_ident(n) for n in old_names)
            new_names = [rename[n] for n in old_names]
            if soft_col:
                new_names = new_names + [soft_col]
            new_q = ", ".join(_quote_ident(n) for n in new_names)

            rows = conn.execute(
                f"SELECT {old_q} FROM {_quote_ident(table)}"
            ).fetchall()
            placeholders = ", ".join("?" for _ in new_names)
            insert_sql = (
                f"INSERT INTO {_quote_ident(tmp)} ({new_q}) VALUES ({placeholders})"
            )
            for row in rows:
                values = list(row)
                if coded_values and text_code_maps:
                    for i, old_name in enumerate(old_names):
                        if old_name in text_code_maps and values[i] is not None:
                            values[i] = text_code_maps[old_name].get(
                                str(values[i]), values[i]
                            )
                if soft_col:
                    values.append(0)
                conn.execute(insert_sql, values)

            conn.execute(f"DROP TABLE {_quote_ident(table)}")
            conn.execute(
                f"ALTER TABLE {_quote_ident(tmp)} RENAME TO {_quote_ident(table)}"
            )

        conn.commit()
    finally:
        conn.close()

    return {
        "src": str(src),
        "dst": str(dst),
        "column_renames": column_renames,
        "value_maps": value_maps,
        "drop_fks": drop_fks,
        "soft_delete": soft_delete,
        "cryptic_names": cryptic_names,
        "coded_values": coded_values,
        "seed": seed,
        "notes": notes,
    }
