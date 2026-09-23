from collections.abc import AsyncGenerator
from pathlib import Path
import logging

from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.config.settings import get_settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _sqlite_connect_args(url: str) -> dict:
    if not _is_sqlite(url):
        return {}
    # SQLite needs an explicit busy timeout + WAL on Windows or concurrent
    # FastAPI requests (scan + UI polling) will hit "database is locked".
    return {"timeout": 60.0, "check_same_thread": False}


def _set_sqlite_pragma(dbapi_conn, connection_record) -> None:  # noqa: ARG001
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=60000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.metadata_database_url
        _engine = create_async_engine(
            url,
            echo=settings.debug,
            connect_args=_sqlite_connect_args(url),
        )
        if _is_sqlite(url):
            event.listen(_engine.sync_engine, "connect", _set_sqlite_pragma)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


def reset_engine() -> None:
    """Drop cached engine/session factory (tests)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


class _SessionFactoryProxy:
    def __call__(self, *args, **kwargs):
        return get_session_factory()(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(get_session_factory(), name)


async_session_factory = _SessionFactoryProxy()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        try:
            yield session
        except (HTTPException, StarletteHTTPException):
            await session.commit()
            raise
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


def _alembic_config():
    from alembic.config import Config

    settings = get_settings()
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", settings.metadata_database_url)
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "src" / "storage" / "migrations"))
    return cfg


def _stamp_legacy_if_needed(cfg) -> None:
    """Existing installs used create_all without alembic_version — stamp at 002."""
    from alembic import command
    from sqlalchemy import create_engine

    url = cfg.get_main_option("sqlalchemy.url")
    if not url:
        return
    sync_url = (
        url.replace("sqlite+aiosqlite://", "sqlite://", 1)
        .replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    engine: Engine = create_engine(sync_url)
    try:
        tables = set(inspect(engine).get_table_names())
        if not tables or "alembic_version" in tables:
            return
        if "connections" in tables:
            command.stamp(cfg, "002_chat_sessions")
    finally:
        engine.dispose()


def _run_alembic_upgrade() -> None:
    from alembic import command

    cfg = _alembic_config()
    _stamp_legacy_if_needed(cfg)
    command.upgrade(cfg, "head")


async def run_migrations() -> None:
    import asyncio

    await asyncio.to_thread(_run_alembic_upgrade)


async def init_db() -> None:
    from src.auth.service import bootstrap_admin
    from src.storage.models import Base

    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.faiss_dir.mkdir(parents=True, exist_ok=True)

    try:
        await run_migrations()
    except Exception:
        logger.exception("Alembic upgrade failed; falling back to create_all")
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    factory = get_session_factory()
    async with factory() as session:
        await bootstrap_admin(session)
        await session.commit()
