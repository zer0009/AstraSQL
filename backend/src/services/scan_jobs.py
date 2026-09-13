"""In-memory schema scan job registry (single-process on-prem)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class ScanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ScanJob:
    id: str
    connection_id: str
    connection_name: str
    status: ScanStatus = ScanStatus.PENDING
    phase: str = "queued"
    message: str = "Queued"
    current_table: Optional[str] = None
    tables_total: int = 0
    tables_done: int = 0
    tables_cached: list[str] = field(default_factory=list)
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    last_scanned_at: Optional[datetime] = None

    @property
    def percent(self) -> int:
        if self.tables_total <= 0:
            if self.status == ScanStatus.COMPLETED:
                return 100
            if self.status == ScanStatus.RUNNING and self.phase in (
                "writing",
                "indexing",
                "enriching",
            ):
                return 90 if self.phase != "enriching" else 95
            return 5 if self.status == ScanStatus.RUNNING else 0
        if self.status == ScanStatus.RUNNING and self.phase == "enriching":
            # Enrich phase: map table progress into 85–99% after schema scan.
            base = 85
            span = 14
            done = min(self.tables_done, self.tables_total)
            return min(99, base + int(round(span * done / self.tables_total)))
        return min(100, int(round(100 * self.tables_done / self.tables_total)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "connection_id": self.connection_id,
            "connection_name": self.connection_name,
            "status": self.status.value,
            "phase": self.phase,
            "message": self.message,
            "current_table": self.current_table,
            "tables_total": self.tables_total,
            "tables_done": self.tables_done,
            "tables_cached": list(self.tables_cached[-20:]),
            "percent": self.percent,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "last_scanned_at": (
                self.last_scanned_at.isoformat() if self.last_scanned_at else None
            ),
        }


_jobs: dict[str, ScanJob] = {}
_by_connection: dict[str, str] = {}
_lock = asyncio.Lock()


def get_job(job_id: str) -> Optional[ScanJob]:
    return _jobs.get(job_id)


def get_job_for_connection(connection_id: str) -> Optional[ScanJob]:
    job_id = _by_connection.get(connection_id)
    if not job_id:
        return None
    return _jobs.get(job_id)


def list_active_jobs() -> list[ScanJob]:
    return [
        j
        for j in _jobs.values()
        if j.status in (ScanStatus.PENDING, ScanStatus.RUNNING)
    ]


def list_recent_jobs(limit: int = 20) -> list[ScanJob]:
    jobs = sorted(
        _jobs.values(),
        key=lambda j: j.started_at
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return jobs[:limit]


async def create_job(connection_id: str, connection_name: str) -> ScanJob:
    async with _lock:
        existing_id = _by_connection.get(connection_id)
        if existing_id:
            existing = _jobs.get(existing_id)
            if existing and existing.status in (
                ScanStatus.PENDING,
                ScanStatus.RUNNING,
            ):
                raise RuntimeError(
                    f"A schema scan is already running for this connection "
                    f"({existing.percent}% — {existing.message})"
                )

        job = ScanJob(
            id=str(uuid.uuid4()),
            connection_id=connection_id,
            connection_name=connection_name,
            started_at=datetime.now(timezone.utc),
        )
        _jobs[job.id] = job
        _by_connection[connection_id] = job.id
        return job


def update_job(job: ScanJob, **kwargs: Any) -> None:
    for key, value in kwargs.items():
        setattr(job, key, value)
