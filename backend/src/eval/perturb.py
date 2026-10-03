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

            if soft_col:
                notes.append(f"{table}: added {soft_col} column")

            tmp = f"__pert_{table}"
            # Avoid collision if tmp exists.
            while tmp in tables or tmp in _table_names(conn):
                tmp = tmp + "_x"

            # SQLite allows at most one PRIMARY KEY clause in CREATE TABLE;
            # composite keys from PRAGMA are collapsed to a table-level PK list.
            pk_cols = [
                old_names[i]
                for i, c in enumerate(cols)
                if int(c[5] or 0) > 0
            ]
            cleaned_defs: list[str] = []
            for _cid, name, ctype, notnull, dflt, pk in cols:
                new_name = rename.get(name, name)
                piece = f"{_quote_ident(new_name)} {_sql_type(ctype)}"
                if notnull and int(pk or 0) == 0:
                    piece += " NOT NULL"
                if dflt is not None and int(pk or 0) == 0:
                    piece += f" DEFAULT {dflt}"
                cleaned_defs.append(piece)
            if soft_col:
                cleaned_defs.append(f"{_quote_ident(soft_col)} INTEGER DEFAULT 0")
            if pk_cols:
                pk_q = ", ".join(_quote_ident(rename.get(c, c)) for c in pk_cols)
                cleaned_defs.append(f"PRIMARY KEY ({pk_q})")
            for fk in fks:
                # id, seq, table, from, to, on_update, on_delete, match
                src_col = rename.get(fk[3], fk[3])
                ref_table = fk[2]
                ref_col = fk[4]
                cleaned_defs.append(
                    f"FOREIGN KEY ({_quote_ident(src_col)}) "
                    f"REFERENCES {_quote_ident(ref_table)}({_quote_ident(ref_col)})"
                )
            create_sql = (
                f"CREATE TABLE {_quote_ident(tmp)} ({', '.join(cleaned_defs)})"
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


def inflate_schema(
    target_sqlite: str | Path,
    donor_sqlites: list[str | Path],
    dst_path: str | Path,
    *,
    prefix_tables: bool = True,
) -> dict[str, Any]:
    """Graft tables from donor DBs into a copy of ``target_sqlite``.

    Used to stress-test large-schema retrieval (100+ tables) while keeping the
    target DB's gold questions valid (target tables keep original names).
    """
    target = Path(target_sqlite)
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, dst)

    grafted: list[dict[str, str]] = []
    conn = sqlite3.connect(str(dst))
    try:
        existing = set(_table_names(conn))
        for donor_path in donor_sqlites:
            donor = Path(donor_path)
            if not donor.exists():
                continue
            # Copy via a separate connection to avoid ATTACH/WAL lock issues.
            dconn = sqlite3.connect(str(donor))
            try:
                donor_tables = _table_names(dconn)
                for table in donor_tables:
                    new_name = (
                        f"{donor.stem}__{table}" if prefix_tables else table
                    )
                    base = new_name
                    n = 2
                    while new_name in existing:
                        new_name = f"{base}_{n}"
                        n += 1
                    try:
                        cols = _column_info(dconn, table)
                        col_defs = []
                        col_names = []
                        for _cid, name, ctype, notnull, _dflt, pk in cols:
                            col_names.append(name)
                            parts = [f"{_quote_ident(name)} {_sql_type(ctype)}"]
                            if pk:
                                parts.append("PRIMARY KEY")
                            elif notnull:
                                parts.append("NOT NULL")
                            col_defs.append(" ".join(parts))
                        conn.execute(
                            f"CREATE TABLE {_quote_ident(new_name)} "
                            f"({', '.join(col_defs)})"
                        )
                        rows = dconn.execute(
                            f"SELECT * FROM {_quote_ident(table)} LIMIT 50"
                        ).fetchall()
                        if rows and col_names:
                            placeholders = ", ".join("?" for _ in col_names)
                            col_q = ", ".join(_quote_ident(c) for c in col_names)
                            conn.executemany(
                                f"INSERT INTO {_quote_ident(new_name)} ({col_q}) "
                                f"VALUES ({placeholders})",
                                rows,
                            )
                        existing.add(new_name)
                        grafted.append(
                            {
                                "donor": str(donor),
                                "source_table": table,
                                "table": new_name,
                            }
                        )
                    except sqlite3.Error as exc:
                        grafted.append(
                            {
                                "donor": str(donor),
                                "source_table": table,
                                "error": str(exc),
                            }
                        )
            finally:
                dconn.close()
            conn.commit()
        conn.commit()
    finally:
        conn.close()

    return {
        "src": str(target),
        "dst": str(dst),
        "grafted_tables": len([g for g in grafted if "table" in g]),
        "grafted": grafted,
    }
