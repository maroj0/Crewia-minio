from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from service.database import JobRow, create_session_factory, init_db


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobRecord:
    job_id: str
    status: JobStatus
    user_story: str
    created_at: str
    updated_at: str
    error: str | None = None
    result_summary: str | None = None
    artifacts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "user_story": self.user_story,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "result_summary": self.result_summary,
            "artifacts": self.artifacts,
        }

    @classmethod
    def from_row(cls, row: JobRow) -> JobRecord:
        return cls(
            job_id=row.job_id,
            status=JobStatus(row.status),
            user_story=row.user_story,
            created_at=_format_dt(row.created_at),
            updated_at=_format_dt(row.updated_at),
            error=row.error,
            result_summary=row.result_summary,
            artifacts=row.artifacts or [],
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_dt(value: datetime | str | None) -> str:
    if value is None:
        return _utc_now().isoformat()
    if isinstance(value, str):
        return value
    return value.isoformat()


class JobStore:
    def __init__(self, database_url: str) -> None:
        self._session_factory, self._engine = create_session_factory(database_url)
        self._lock = asyncio.Lock()

    def initialize(self) -> None:
        init_db(self._engine)

    def _create_job_sync(self, user_story: str) -> JobRecord:
        job_id = str(uuid4())
        now = _utc_now()
        with self._session_factory() as session:
            row = JobRow(
                job_id=job_id,
                status=JobStatus.PENDING.value,
                user_story=user_story,
                created_at=now,
                updated_at=now,
                artifacts=[],
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return JobRecord.from_row(row)

    def _get_job_sync(self, job_id: str) -> JobRecord | None:
        with self._session_factory() as session:
            row = session.get(JobRow, job_id)
            return JobRecord.from_row(row) if row else None

    def _update_job_sync(self, job_id: str, **updates: Any) -> JobRecord | None:
        with self._session_factory() as session:
            row = session.get(JobRow, job_id)
            if not row:
                return None
            for key, value in updates.items():
                if key == "status" and isinstance(value, JobStatus):
                    value = value.value
                if hasattr(row, key):
                    setattr(row, key, value)
            row.updated_at = _utc_now()
            session.commit()
            session.refresh(row)
            return JobRecord.from_row(row)

    def _list_jobs_sync(
        self,
        status: JobStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[JobRecord], int]:
        with self._session_factory() as session:
            query = select(JobRow)
            count_query = select(func.count()).select_from(JobRow)
            if status:
                query = query.where(JobRow.status == status.value)
                count_query = count_query.where(JobRow.status == status.value)
            query = query.order_by(JobRow.created_at.desc()).limit(limit).offset(offset)
            rows = session.scalars(query).all()
            total = session.scalar(count_query) or 0
            return [JobRecord.from_row(row) for row in rows], total

    async def create_job(self, user_story: str) -> JobRecord:
        async with self._lock:
            return await asyncio.to_thread(self._create_job_sync, user_story)

    async def get_job(self, job_id: str) -> JobRecord | None:
        return await asyncio.to_thread(self._get_job_sync, job_id)

    async def update_job(self, job_id: str, **updates: Any) -> JobRecord | None:
        async with self._lock:
            return await asyncio.to_thread(self._update_job_sync, job_id, **updates)

    async def list_jobs(
        self,
        status: JobStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[JobRecord], int]:
        return await asyncio.to_thread(self._list_jobs_sync, status, limit, offset)
