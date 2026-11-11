"""
Worker-side job state tracking.

Celery signals fire in the worker around every task run. Each handler
updates the job row, so the database always reflects what workers are doing
(no polling of the result backend needed).
"""

import logging

from celery.exceptions import Retry
from celery.signals import task_failure, task_prerun, task_retry, task_success
from sqlalchemy import select, update

from app.core.database import sync_session_factory
from app.models.job import Job, JobStatus, utcnow
from app.tasks.base import PermanentError, RetriesExhausted, job_id_from_task_id

log = logging.getLogger(__name__)


def _update(task_id: str | None, **values) -> None:
    job_id = job_id_from_task_id(task_id)
    if job_id is None:
        return  # not a Pulse job (e.g. a task started by hand)
    with sync_session_factory()() as session:
        session.execute(update(Job).where(Job.id == job_id).values(**values))
        session.commit()


@task_prerun.connect
def on_prerun(task_id=None, task=None, **_):
    job_id = job_id_from_task_id(task_id)
    if job_id is None:
        return
    with sync_session_factory()() as session:
        job = session.scalar(select(Job).where(Job.id == job_id))
        if job is None:
            log.warning("Task %s refers to missing job %s", task_id, job_id)
            return
        # Make the per-job retry budget visible to PulseTask for this run.
        task.request.job_max_retries = job.max_retries
        job.status = JobStatus.RUNNING
        job.attempts = task.request.retries + 1
        job.started_at = job.started_at or utcnow()
        job.next_retry_at = None
        session.commit()


@task_success.connect
def on_success(sender=None, result=None, **_):
    _update(
        sender.request.id,
        status=JobStatus.COMPLETED,
        result=result,
        error_message=None,
        completed_at=utcnow(),
    )


@task_retry.connect
def on_retry(request=None, reason=None, **_):
    exc = reason.exc if isinstance(reason, Retry) and reason.exc else reason
    eta = getattr(reason, "when", None)
    values = {"status": JobStatus.RETRYING, "error_message": str(exc)}
    if hasattr(eta, "replace"):  # datetime
        values["next_retry_at"] = eta.replace(tzinfo=None)
    _update(request.id, **values)


@task_failure.connect
def on_failure(task_id=None, exception=None, **_):
    status = JobStatus.DEAD_LETTER if isinstance(exception, RetriesExhausted) else JobStatus.FAILED
    if not isinstance(exception, (RetriesExhausted, PermanentError)):
        log.error("Task %s crashed with an unexpected error: %r", task_id, exception)
    _update(task_id, status=status, error_message=str(exception), completed_at=utcnow(), next_retry_at=None)
