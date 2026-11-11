"""Public task names → Celery task name and payload schema. Single source of truth for the API."""

from dataclasses import dataclass

from pydantic import BaseModel

from app.schemas.job import GenerateReportPayload, ProcessImagePayload, ProcessWebhookPayload, SendEmailPayload


@dataclass(frozen=True)
class TaskSpec:
    celery_name: str
    payload_model: type[BaseModel]


TASKS: dict[str, TaskSpec] = {
    "send_email": TaskSpec("pulse.send_email", SendEmailPayload),
    "generate_report": TaskSpec("pulse.generate_report", GenerateReportPayload),
    "process_webhook": TaskSpec("pulse.process_webhook", ProcessWebhookPayload),
    "process_image": TaskSpec("pulse.process_image", ProcessImagePayload),
}

# Priority → Celery queue. Run dedicated workers per queue for real prioritisation, e.g.
#   celery -A app.celery_app worker -Q critical,high
#   celery -A app.celery_app worker -Q default,low
QUEUES = ("critical", "high", "default", "low")
