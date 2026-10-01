import sqlite3
from pathlib import Path

from src.eval.perturb import perturb_sqlite


def _make_src(tmp_path: Path) -> Path:
    src = tmp_path / "src.sqlite"
    conn = sqlite3.connect(src)
    try:
        conn.execute(
            "CREATE TABLE customers ("
            "id INTEGER PRIMARY KEY, "
            "status TEXT, "
            "name TEXT)"
        )
        conn.execute(
            "INSERT INTO customers (id, status, name) VALUES "
            "(1, 'active', 'Alice'), (2, 'inactive', 'Bob'), (3, 'active', 'Cara')"
        )
        conn.execute(
            "CREATE TABLE orders ("
            "id INTEGER PRIMARY KEY, "
            "customer_id INTEGER, "
            "amount REAL, "
            "FOREIGN KEY (customer_id) REFERENCES customers(id))"
        )
        conn.execute(
            "INSERT INTO orders (id, customer_id, amount) VALUES (1, 1, 10.0), (2, 2, 20.0)"
        )
        conn.commit()
    finally:
        conn.close()
    return src


def test_perturb_sqlite_renames_codes_soft_delete_drop_fks(tmp_path: Path):
    src = _make_src(tmp_path)
    dst = tmp_path / "dst.sqlite"
    meta = perturb_sqlite(
        src,
        dst,
        cryptic_names=True,
        coded_values=True,
        drop_fks=True,
        soft_delete=True,
        seed=0,
    )

    assert dst.exists()
    assert "customers" in meta["column_renames"]
    assert "status" in meta["column_renames"]["customers"]
    assert meta["column_renames"]["customers"]["status"] != "status"
    assert any("customers.status" == k or k.endswith(".status") for k in meta["value_maps"])
    assert meta["notes"]

    conn = sqlite3.connect(dst)
    try:
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(customers)").fetchall()
        }
        # Original names gone; soft-delete present.
        assert "status" not in cols
        assert "is_deleted" in cols or "soft_delete" in cols
        fks = conn.execute("PRAGMA foreign_key_list(orders)").fetchall()
        assert fks == []
        # Coded values for status.
        renamed_status = meta["column_renames"]["customers"]["status"]
        vals = {
            r[0]
            for r in conn.execute(
                f'SELECT DISTINCT "{renamed_status}" FROM customers'
            ).fetchall()
        }
        assert vals  # non-empty
        assert all(str(v).startswith("C") for v in vals)
    finally:
        conn.close()


def test_perturb_sqlite_can_disable_flags(tmp_path: Path):
    src = _make_src(tmp_path)
    dst = tmp_path / "plain.sqlite"
    meta = perturb_sqlite(
        src,
        dst,
        cryptic_names=False,
        coded_values=False,
        drop_fks=False,
        soft_delete=False,
        seed=1,
    )
    assert meta["column_renames"] == {}
    assert meta["value_maps"] == {}
    conn = sqlite3.connect(dst)
    try:
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(customers)").fetchall()
        }
        assert "status" in cols
        assert "is_deleted" not in cols
        fks = conn.execute("PRAGMA foreign_key_list(orders)").fetchall()
        assert len(fks) >= 1
    finally:
        conn.close()
