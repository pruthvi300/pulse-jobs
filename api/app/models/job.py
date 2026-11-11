"""
Job table: the source of truth for job state.

The API inserts a row (PENDING) and publishes a Celery message. Workers
update the row through Celery signals (see app/tasks/state.py):

    PENDING ──► RUNNING ──► COMPLETED
                  │  ▲
                  ▼  │ (backoff)
               RETRYING
                  │
                  ├──► DEAD_LETTER   transient error, retries exhausted
                  └──► FAILED        permanent error / bug, not retried

FAILED and DEAD_LETTER jobs can be re-queued with POST /jobs/{id}/retry.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC, matching the TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD_LETTER = "dead_letter"


class JobPriority(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    DEFAULT = "default"
    LOW = "low"


TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.DEAD_LETTER}


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    task_name: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Celery task id of the current run. Retries keep the same id; a manual retry gets a new one.
    celery_task_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)

    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING, index=True)
    priority: Mapped[JobPriority] = mapped_column(Enum(JobPriority), default=JobPriority.DEFAULT)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    result: Mapped[dict | list | str | int | float | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Job {self.id} {self.task_name} ({self.status.value})>"
