import numpy as np
import pytest

from src.context.golden_records import GoldenRecordsStore, _normalize
from src.context.pack import export_pack, import_pack
from src.storage.crypto import encrypt_password
from src.storage.models import Connection


@pytest.fixture
def fake_embed(monkeypatch, tmp_path):
    async def _embed(self, text):  # noqa: ARG001
        vec = np.ones((1, 8), dtype=np.float32)
        return _normalize(vec)

    monkeypatch.setattr(GoldenRecordsStore, "_embed_text", _embed)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    from src.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _connection(db_session) -> Connection:
    row = Connection(
        name="shop",
        db_type="postgresql",
        host="localhost",
        port=5432,
        database="shop",
        username="u",
        encrypted_password=encrypt_password("p"),
        ssl_enabled=False,
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_pack_round_trip(db_session, fake_embed):
    connection = await _connection(db_session)
    source = {
        "version": 1,
        "enrichments": [
            {
                "table_name": "customers",
                "column_name": "status",
                "description": "A active, I inactive, T test",
                "alias": "customer status",
                "example_values": '["A","I"]',
            }
        ],
        "rules": [{"content": "active customers means status = 'A'"}],
        "goldens": [
            {
                "question": "How many customers live in Texas?",
                "sql": "SELECT COUNT(*) FROM customers WHERE state = 'TX'",
            }
        ],
    }
    counts = await import_pack(db_session, connection.id, source)
    assert counts == {"enrichments": 1, "rules": 1, "goldens": 1}

    exported = await export_pack(db_session, connection.id)
    assert exported["version"] == 1
    assert len(exported["enrichments"]) == 1
    assert exported["enrichments"][0]["table_name"] == "customers"
    assert exported["rules"][0]["content"] == "active customers means status = 'A'"
    assert exported["goldens"][0]["question"].startswith("How many customers")

    empty = Connection(
        name="other",
        db_type="postgresql",
        host="localhost",
        port=5432,
        database="shop",
        username="u",
        encrypted_password=encrypt_password("p"),
        ssl_enabled=False,
    )
    db_session.add(empty)
    await db_session.flush()
    await import_pack(db_session, empty.id, exported)
    second = await export_pack(db_session, empty.id)
    assert len(second["goldens"]) == 1
    assert len(second["rules"]) == 1
    assert len(second["enrichments"]) == 1


def test_pack_rejects_unknown_version():
    from src.context.pack import _as_pack

    with pytest.raises(ValueError, match="Unsupported pack version"):
        _as_pack({"version": 99, "enrichments": [], "rules": [], "goldens": []})
