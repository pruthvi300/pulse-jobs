"""
Job REST API.

POST   /jobs/               submit (idempotent with idempotency_key)
GET    /jobs/{id}           job state (read from PostgreSQL, kept current by workers)
GET    /jobs/               list with filters + pagination
GET    /jobs/stats/summary  counts per status
POST   /jobs/{id}/retry     re-queue a FAILED or DEAD_LETTER job
"""

import asyncio
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.core.config import settings
from app.core.database import get_db
from app.models.job import Job, JobPriority, JobStatus, utcnow
from app.schemas.job import JobCreate, JobListResponse, JobResponse, JobStats
from app.tasks.registry import TASKS

log = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["Jobs"])
Db = Annotated[AsyncSession, Depends(get_db)]


def _publish(job: Job) -> str:
    """Send the job to its priority queue. Blocking (broker I/O): call via a thread."""
    task_id = f"job-{job.id}-{uuid.uuid4().hex[:12]}"
    celery_app.send_task(
        TASKS[job.task_name].celery_name,
        kwargs=job.payload or {},
        queue=job.priority.value,
        task_id=task_id,
    )
    return task_id


async def _enqueue(db: AsyncSession, job: Job) -> None:
    """Publish and record the task id. If the broker is unreachable, mark the job FAILED and return 503."""
    try:
        job.celery_task_id = await asyncio.to_thread(_publish, job)
    except Exception as exc:
        log.exception("Could not publish job %s", job.id)
        job.status = JobStatus.FAILED
        job.error_message = f"Could not reach the job queue: {exc}"
        job.completed_at = utcnow()
        await db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Job queue unavailable; job marked failed") from exc
    await db.commit()


async def _get_job(db: AsyncSession, job_id: int) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id} not found")
    return job


@router.post("/", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(job_in: JobCreate, db: Db, response: Response):
    """
    Submit a job. With an `idempotency_key`, repeating the request returns the
    original job (status 200) instead of creating a duplicate.
    """
    spec = TASKS.get(job_in.task_name)
    if spec is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown task: {job_in.task_name}. Available: {list(TASKS)}")
    try:
        payload = spec.payload_model.model_validate(job_in.payload).model_dump(mode="json")
    except ValidationError as exc:
        raise HTTPException(
            422,
            [{"loc": ["body", "payload", *e["loc"]], "msg": e["msg"], "type": e["type"]} for e in exc.errors()],
        ) from exc

    if job_in.idempotency_key:
        existing = await db.scalar(select(Job).where(Job.idempotency_key == job_in.idempotency_key))
        if existing:
            response.status_code = status.HTTP_200_OK
            return existing

    job = Job(
        task_name=job_in.task_name,
        payload=payload,
        priority=job_in.priority,
        idempotency_key=job_in.idempotency_key,
        max_retries=settings.DEFAULT_MAX_RETRIES if job_in.max_retries is None else job_in.max_retries,
        status=JobStatus.PENDING,
    )
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent request with the same idempotency key won the race.
        await db.rollback()
        existing = await db.scalar(select(Job).where(Job.idempotency_key == job_in.idempotency_key))
        if existing is None:
            raise
        response.status_code = status.HTTP_200_OK
        return existing

    await _enqueue(db, job)
    return job


@router.get("/stats/summary", response_model=JobStats)
async def get_job_stats(db: Db):
    rows = (await db.execute(select(Job.status, func.count(Job.id)).group_by(Job.status))).all()
    counts = {s.value: n for s, n in rows}
    return JobStats(total_jobs=sum(counts.values()), **counts)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: int, db: Db):
    return await _get_job(db, job_id)


@router.get("/", response_model=JobListResponse)
async def list_jobs(
    db: Db,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    task_name: str | None = None,
    priority: JobPriority | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    filters = []
    if status_filter:
        filters.append(Job.status == status_filter)
    if task_name:
        filters.append(Job.task_name == task_name)
    if priority:
        filters.append(Job.priority == priority)

    total = await db.scalar(select(func.count(Job.id)).where(*filters))
    jobs = (
        await db.scalars(
            select(Job)
            .where(*filters)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return JobListResponse(jobs=jobs, total=total or 0, page=page, page_size=page_size)


@router.post("/{job_id}/retry", response_model=JobResponse)
async def retry_job(job_id: int, db: Db):
    """Re-queue a FAILED or DEAD_LETTER job with a fresh retry budget."""
    job = await _get_job(db, job_id)
    if job.status not in (JobStatus.FAILED, JobStatus.DEAD_LETTER):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Only failed or dead-letter jobs can be retried (status: {job.status.value})"
        )
    job.status = JobStatus.PENDING
    job.attempts = 0
    job.error_message = None
    job.result = None
    job.started_at = None
    job.completed_at = None
    job.next_retry_at = None
    await _enqueue(db, job)
    return job
