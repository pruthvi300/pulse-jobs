"""
Celery application shared by the API (publishes) and workers (consume).

Start a worker with:
    celery -A app.celery_app worker --loglevel=info
"""

from celery import Celery
from kombu import Queue

from app.core.config import settings
from app.tasks.registry import QUEUES

celery_app = Celery(
    "pulse",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    # Explicit module list: autodiscover_tasks(["app.tasks"]) looks for
    # app/tasks/tasks.py, which doesn't exist, so workers registered nothing.
    include=["app.tasks.jobs", "app.tasks.state"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Job state lives in PostgreSQL; results in Redis are only for Flower/debugging.
    result_expires=3600,
    task_time_limit=300,
    task_soft_time_limit=240,
    # Acknowledge after the task finishes, so a crashed worker's job is redelivered.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_queues=[Queue(name) for name in QUEUES],
    task_default_queue="default",
    # Fail fast when the broker is down instead of blocking the API request.
    broker_connection_timeout=settings.BROKER_PUBLISH_TIMEOUT_SECONDS,
    task_publish_retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.5, "interval_max": 1},
    # Redis redelivers unacked tasks after this; keep it above the longest retry countdown + runtime.
    broker_transport_options={"visibility_timeout": settings.CELERY_VISIBILITY_TIMEOUT_SECONDS},
)
