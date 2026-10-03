"""API coverage for evidence, public settings flags, semantic layer."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.api.schemas import QueryRequest
from src.storage.crypto import encrypt_password
from src.storage.database import get_engine
from src.storage.models import Connection


@pytest.mark.asyncio
async def test_public_settings_includes_behavior_flags(authed_client: AsyncClient):
    resp = await authed_client.get("/api/settings/public")
    assert resp.status_code == 200
    data = resp.json()
    assert "execution_evidence_gate" in data
    assert "merge_interpret_generate" in data
    assert "ambiguity_policy" in data
    assert data["sse_row_preview_limit"] == 100


def test_query_request_accepts_evidence():
    body = QueryRequest(
        connection_id="x",
        question="how many?",
        evidence="active means status=A",
    )
    assert body.evidence == "active means status=A"


@pytest.mark.asyncio
async def test_semantic_layer_and_relationship_approve(authed_client: AsyncClient):
    factory = async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        conn = Connection(
            name="sem-test",
            db_type="postgresql",
            host="localhost",
            port=5432,
            database="db",
            username="u",
            encrypted_password=encrypt_password("p"),
            ssl_enabled=False,
            semantic_layer_json=json.dumps(
                {
                    "relationships": [
                        {
                            "from_table": "orders",
                            "from_col": "customer_id",
                            "to_table": "customers",
                            "to_col": "id",
                            "status": "proposed",
                            "score": 0.9,
                        }
                    ]
                }
            ),
        )
        session.add(conn)
        await session.commit()
        await session.refresh(conn)
        cid = conn.id

    layer = await authed_client.get(f"/api/connections/{cid}/semantic-layer")
    assert layer.status_code == 200
    body = layer.json()
    assert len(body["relationships"]) == 1
    assert body["relationships"][0]["status"] == "proposed"

    patched = await authed_client.patch(
        f"/api/connections/{cid}/relationships/orders/customer_id/customers/id",
        json={"status": "approved"},
    )
    assert patched.status_code == 200
    assert patched.json()["relationships"][0]["status"] == "approved"
    assert any("orders.customer_id" in p for p in patched.json()["join_paths"])


@pytest.mark.asyncio
async def test_agent_graph_endpoint(authed_client: AsyncClient):
    resp = await authed_client.get("/api/settings/agent-graph")
    assert resp.status_code == 200
    data = resp.json()
    assert "mermaid" in data
    assert isinstance(data["nodes"], list)
