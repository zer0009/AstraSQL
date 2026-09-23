import os

# Must be set before importing application modules that call get_settings().
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-not-for-prod!!")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.app import create_app
from src.config.settings import get_settings
from src.storage.database import init_db, reset_engine
from src.storage.models import Base

get_settings.cache_clear()

TEST_NEW_PASSWORD = "CorrectHorse-12"


@pytest_asyncio.fixture
async def app(tmp_path, monkeypatch):
    db_file = (tmp_path / "test.db").resolve().as_posix()
    monkeypatch.setenv("SQLITE_URL", f"sqlite+aiosqlite:///{db_file}")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    reset_engine()
    await init_db()
    yield create_app()
    reset_engine()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def db_engine(tmp_path):
    db_path = tmp_path / "isolated.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def authed_client(client):
    settings = get_settings()
    login = await client.post(
        "/api/auth/login",
        json={
            "username": settings.default_admin_username,
            "password": settings.default_admin_password,
        },
    )
    assert login.status_code == 200
    changed = await client.post(
        "/api/auth/change-password",
        json={
            "current_password": settings.default_admin_password,
            "new_password": TEST_NEW_PASSWORD,
        },
    )
    assert changed.status_code == 200
    yield client
