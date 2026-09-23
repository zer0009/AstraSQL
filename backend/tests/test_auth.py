import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.auth.service import bootstrap_admin
from src.config.settings import get_settings
from src.storage.database import get_engine, init_db
from src.storage.models import User
from tests.conftest import TEST_NEW_PASSWORD


@pytest.mark.asyncio
async def test_alembic_version_is_003_auth(app):  # noqa: ARG001
    engine = get_engine()
    async with engine.connect() as conn:
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    assert version == "003_auth"


@pytest.mark.asyncio
async def test_bootstrap_creates_admin_once(app):  # noqa: ARG001
    settings = get_settings()
    factory = async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        count = await session.scalar(select(func.count()).select_from(User))
        assert count == 1
        user = await session.scalar(select(User).where(User.username == settings.default_admin_username))
        assert user is not None
        assert user.must_change_password is True
        first_hash = user.password_hash

    await init_db()

    async with factory() as session:
        count = await session.scalar(select(func.count()).select_from(User))
        assert count == 1
        user = await session.scalar(select(User).where(User.username == settings.default_admin_username))
        assert user is not None
        assert user.password_hash == first_hash


@pytest.mark.asyncio
async def test_bootstrap_skips_when_users_exist(db_session):
    created = await bootstrap_admin(db_session)
    assert created is True
    await db_session.commit()
    created_again = await bootstrap_admin(db_session)
    assert created_again is False


@pytest.mark.asyncio
async def test_unauthenticated_connections_401(client):
    response = await client.get("/api/connections")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_default_requires_password_change(client):
    settings = get_settings()
    login = await client.post(
        "/api/auth/login",
        json={
            "username": settings.default_admin_username,
            "password": settings.default_admin_password,
        },
    )
    assert login.status_code == 200
    body = login.json()
    assert body["must_change_password"] is True
    assert body["username"] == settings.default_admin_username

    blocked = await client.get("/api/connections")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"

    query = await client.post(
        "/api/query",
        json={"connection_id": "00000000-0000-0000-0000-000000000000", "question": "x"},
    )
    assert query.status_code == 403
    assert query.json()["code"] == "PASSWORD_CHANGE_REQUIRED"


@pytest.mark.asyncio
async def test_change_password_rejects_default_and_short(client):
    settings = get_settings()
    await client.post(
        "/api/auth/login",
        json={
            "username": settings.default_admin_username,
            "password": settings.default_admin_password,
        },
    )

    too_short = await client.post(
        "/api/auth/change-password",
        json={
            "current_password": settings.default_admin_password,
            "new_password": "short",
        },
    )
    assert too_short.status_code == 400

    same_default = await client.post(
        "/api/auth/change-password",
        json={
            "current_password": settings.default_admin_password,
            "new_password": settings.default_admin_password,
        },
    )
    assert same_default.status_code == 400

    ok = await client.post(
        "/api/auth/change-password",
        json={
            "current_password": settings.default_admin_password,
            "new_password": TEST_NEW_PASSWORD,
        },
    )
    assert ok.status_code == 200
    assert ok.json()["must_change_password"] is False

    allowed = await client.get("/api/connections")
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_logout_revokes_session(authed_client):
    allowed = await authed_client.get("/api/connections")
    assert allowed.status_code == 200

    logout = await authed_client.post("/api/auth/logout")
    assert logout.status_code == 200

    denied = await authed_client.get("/api/connections")
    assert denied.status_code == 401


@pytest.mark.asyncio
async def test_login_lockout_after_five_failures(client):
    settings = get_settings()
    for _ in range(5):
        response = await client.post(
            "/api/auth/login",
            json={"username": settings.default_admin_username, "password": "wrong-password"},
        )
        assert response.status_code == 401

    locked = await client.post(
        "/api/auth/login",
        json={
            "username": settings.default_admin_username,
            "password": settings.default_admin_password,
        },
    )
    assert locked.status_code == 423


@pytest.mark.asyncio
async def test_auth_status_and_me(client):
    status = await client.get("/api/auth/status")
    assert status.status_code == 200
    assert status.json()["setup_complete"] is False

    me = await client.get("/api/auth/me")
    assert me.status_code == 401

    settings = get_settings()
    await client.post(
        "/api/auth/login",
        json={
            "username": settings.default_admin_username,
            "password": settings.default_admin_password,
        },
    )
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True

    await client.post(
        "/api/auth/change-password",
        json={
            "current_password": settings.default_admin_password,
            "new_password": TEST_NEW_PASSWORD,
        },
    )
    status = await client.get("/api/auth/status")
    assert status.json()["setup_complete"] is True


@pytest.mark.asyncio
async def test_unknown_user_login_401(client):
    response = await client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "whatever-password"},
    )
    assert response.status_code == 401
