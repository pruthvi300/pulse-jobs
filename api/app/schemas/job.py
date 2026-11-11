"""API request/response models, including one payload model per task."""

from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, HttpUrl

from app.models.job import JobPriority, JobStatus


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


UTCDatetime = Annotated[datetime, AfterValidator(_as_utc)]


# ── Task payloads ────────────────────────────────────────────────────────────
# Validated at submission, so a bad payload is a 422 for the client instead of
# a job that fails (or retries) in the worker.


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SendEmailPayload(_Payload):
    to: EmailStr
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(max_length=100_000)


class GenerateReportPayload(_Payload):
    report_type: str = Field(min_length=1, max_length=50)
    params: dict[str, Any] = Field(default_factory=dict)


class ProcessWebhookPayload(_Payload):
    webhook_url: HttpUrl
    payload: dict[str, Any] = Field(default_factory=dict)


class ProcessImagePayload(_Payload):
    image_url: HttpUrl
    operations: list[str] = Field(default_factory=list, max_length=20)


# ── Jobs ─────────────────────────────────────────────────────────────────────


class JobCreate(BaseModel):
    task_name: str = Field(..., examples=["send_email"])
    payload: dict[str, Any] = Field(
        default_factory=dict, examples=[{"to": "user@example.com", "subject": "Hi", "body": "Hello"}]
    )
    priority: JobPriority = JobPriority.DEFAULT
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    max_retries: int | None = Field(default=None, ge=0, le=10, description="Defaults to the server setting")


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_name: str
    payload: dict | None = None
    status: JobStatus
    priority: JobPriority
    idempotency_key: str | None = None
    celery_task_id: str | None = None
    attempts: int
    max_retries: int
    next_retry_at: UTCDatetime | None = None
    result: Any = None
    error_message: str | None = None
    created_at: UTCDatetime
    started_at: UTCDatetime | None = None
    completed_at: UTCDatetime | None = None


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    total: int
    page: int
    page_size: int


class JobStats(BaseModel):
    total_jobs: int = 0
    pending: int = 0
    running: int = 0
    retrying: int = 0
    completed: int = 0
    failed: int = 0
    dead_letter: int = 0
