from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from src.api.deps import DbSession
from src.api.schemas import (
    ConnectionCreate,
    ConnectionOut,
    ConnectionScanResult,
    ConnectionTestResult,
    ConnectionUpdate,
    ScanJobStatus,
)
from src.providers.database import list_database_types, provider_from_connection
from src.services.scan_jobs import (
    create_job,
    get_job,
    get_job_for_connection,
    list_active_jobs,
    list_recent_jobs,
)
from src.services.scan_runner import run_scan_job
from src.storage.crypto import encrypt_password
from src.storage.models import Connection

router = APIRouter(tags=["connections"])


def _validate_db_type(db_type: str) -> str:
    available = list_database_types()
    key = db_type.lower().strip()
    aliases = {
        "postgres": "postgresql",
        "pg": "postgresql",
        "sqlserver": "mssql",
        "sql_server": "mssql",
    }
    key = aliases.get(key, key)
    if key not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid db_type {db_type!r}. Available: {available}",
        )
    return key


def _to_out(conn: Connection) -> ConnectionOut:
    return ConnectionOut(
        id=conn.id,
        name=conn.name,
        db_type=conn.db_type,
        host=conn.host,
        port=conn.port,
        database=conn.database,
        username=conn.username,
        password_set=bool(conn.encrypted_password),
        ssl_enabled=conn.ssl_enabled,
        last_scanned_at=conn.last_scanned_at,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


async def _get_connection(db: DbSession, connection_id: str) -> Connection:
    conn = await db.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


@router.get("", response_model=list[ConnectionOut])
async def list_connections(db: DbSession) -> list[ConnectionOut]:
    result = await db.execute(select(Connection).order_by(Connection.name))
    return [_to_out(c) for c in result.scalars().all()]


@router.get("/scans", response_model=list[ScanJobStatus])
async def list_scans(active_only: bool = False) -> list[ScanJobStatus]:
    jobs = list_active_jobs() if active_only else list_recent_jobs()
    return [ScanJobStatus(**j.to_dict()) for j in jobs]


@router.post("", response_model=ConnectionOut, status_code=201)
async def create_connection(body: ConnectionCreate, db: DbSession) -> ConnectionOut:
    db_type = _validate_db_type(body.db_type)
    conn = Connection(
        name=body.name,
        db_type=db_type,
        host=body.host,
        port=body.port,
        database=body.database,
        username=body.username,
        encrypted_password=encrypt_password(body.password),
        ssl_enabled=body.ssl_enabled,
    )
    db.add(conn)
    await db.flush()
    # Refresh so server defaults (created_at/updated_at) are loaded in-async;
    # accessing expired attrs in _to_out would raise MissingGreenlet.
    await db.refresh(conn)
    return _to_out(conn)


@router.get("/{connection_id}", response_model=ConnectionOut)
async def get_connection(connection_id: str, db: DbSession) -> ConnectionOut:
    return _to_out(await _get_connection(db, connection_id))


@router.put("/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: str, body: ConnectionUpdate, db: DbSession
) -> ConnectionOut:
    conn = await _get_connection(db, connection_id)
    data = body.model_dump(exclude_unset=True)

    if "db_type" in data and data["db_type"] is not None:
        data["db_type"] = _validate_db_type(data["db_type"])

    if "password" in data:
        password = data.pop("password")
        if password is not None and password != "":
            conn.encrypted_password = encrypt_password(password)

    for field, value in data.items():
        setattr(conn, field, value)

    await db.flush()
    # onupdate=func.now() expires updated_at; refresh before sync attribute access.
    await db.refresh(conn)
    return _to_out(conn)


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(connection_id: str, db: DbSession) -> None:
    conn = await _get_connection(db, connection_id)
    await db.delete(conn)
    await db.flush()


@router.post("/{connection_id}/test", response_model=ConnectionTestResult)
async def test_connection(connection_id: str, db: DbSession) -> ConnectionTestResult:
    conn = await _get_connection(db, connection_id)
    provider = provider_from_connection(conn)
    try:
        ok = await provider.test_connection()
        return ConnectionTestResult(
            ok=ok,
            message="Connection successful" if ok else "Connection failed",
        )
    except Exception as exc:
        return ConnectionTestResult(ok=False, message=str(exc))
    finally:
        await provider.close()


@router.post(
    "/{connection_id}/scan",
    response_model=ConnectionScanResult,
    status_code=202,
)
async def scan_connection(
    connection_id: str,
    db: DbSession,
) -> ConnectionScanResult:
    """Start a background schema scan. Poll GET .../scan for progress."""
    conn = await _get_connection(db, connection_id)
    try:
        job = await create_job(conn.id, conn.name)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Fire-and-forget on the app event loop — survives navigation / request end.
    asyncio.create_task(run_scan_job(job))

    return ConnectionScanResult(
        job_id=job.id,
        connection_id=conn.id,
        status=job.status.value,
        message="Schema scan started in the background",
    )


@router.get("/{connection_id}/scan", response_model=ScanJobStatus)
async def get_scan_status(connection_id: str, db: DbSession) -> ScanJobStatus:
    await _get_connection(db, connection_id)
    job = get_job_for_connection(connection_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="No scan job found for this connection yet",
        )
    return ScanJobStatus(**job.to_dict())


@router.get("/{connection_id}/scan/{job_id}", response_model=ScanJobStatus)
async def get_scan_job(
    connection_id: str, job_id: str, db: DbSession
) -> ScanJobStatus:
    await _get_connection(db, connection_id)
    job = get_job(job_id)
    if job is None or job.connection_id != connection_id:
        raise HTTPException(status_code=404, detail="Scan job not found")
    return ScanJobStatus(**job.to_dict())
