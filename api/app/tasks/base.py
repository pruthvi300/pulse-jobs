"""
Retry policy shared by every Pulse task.

Tasks raise:
- TransientError  → retried with exponential backoff + full jitter, up to the
                    job's max_retries; then the job goes to DEAD_LETTER.
- PermanentError  → not retried; the job is marked FAILED.
Any other exception is treated as a bug: not retried, marked FAILED.
"""

import random
import re

from celery import Task

from app.core.config import settings

JOB_TASK_ID = re.compile(r"^job-(\d+)-")


class TransientError(Exception):
    """A failure that may succeed if tried again (timeouts, 5xx, rate limits)."""


class PermanentError(Exception):
    """A failure that will not change on retry (bad input, 4xx)."""


class RetriesExhausted(Exception):
    """Raised instead of retrying once the job's retry budget is spent."""


def job_id_from_task_id(task_id: str | None) -> int | None:
    match = JOB_TASK_ID.match(task_id or "")
    return int(match.group(1)) if match else None


def backoff_delay(retries: int) -> float:
    """Exponential backoff with full jitter: uniform(0, min(base * 2**n, max))."""
    cap = min(settings.RETRY_BACKOFF_BASE_SECONDS * (2**retries), settings.RETRY_BACKOFF_MAX_SECONDS)
    return random.uniform(0, cap)


class PulseTask(Task):
    abstract = True
    # The job row holds the real limit; app/tasks/state.py copies it onto the
    # request before each run (request.job_max_retries).
    max_retries = settings.DEFAULT_MAX_RETRIES

    def __call__(self, *args, **kwargs):
        try:
            return self.run(*args, **kwargs)
        except TransientError as exc:
            limit = getattr(self.request, "job_max_retries", None)
            limit = self.max_retries if limit is None else limit
            if self.request.retries >= limit:
                raise RetriesExhausted(f"Gave up after {self.request.retries + 1} attempts: {exc}") from exc
            raise self.retry(exc=exc, countdown=backoff_delay(self.request.retries), max_retries=limit) from exc
