"""
Simulated background tasks.

They sleep and fail randomly to exercise the retry machinery. Swap the
bodies for real integrations (SMTP, HTTP, PIL, S3) without touching the
retry/state code: raise TransientError for things worth retrying and
PermanentError for things that are not.
"""

import logging
import random
import time

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import settings
from app.tasks.base import PermanentError, PulseTask, TransientError

log = logging.getLogger(__name__)

# Failure rates and latency for the simulations; tests patch these, load tests set them via env.
SIMULATED_FAILURE_RATE = {
    "send_email": settings.SIMULATED_EMAIL_FAILURE_RATE,
    "process_webhook": settings.SIMULATED_WEBHOOK_FAILURE_RATE,
}
SIMULATED_LATENCY_SECONDS = settings.SIMULATED_LATENCY_SCALE


def _simulate_work(seconds: float = 1.0) -> None:
    time.sleep(seconds * SIMULATED_LATENCY_SECONDS)


@shared_task(bind=True, base=PulseTask, name="pulse.send_email")
def send_email(self, to: str, subject: str, body: str) -> dict:
    log.info("[%s] sending email to %s (attempt %d)", self.request.id, to, self.request.retries + 1)
    if random.random() < SIMULATED_FAILURE_RATE["send_email"]:
        raise TransientError("SMTP server temporarily unavailable")
    _simulate_work(2)
    return {"status": "sent", "recipient": to, "message_id": f"msg_{random.randint(1000, 9999)}"}


@shared_task(bind=True, base=PulseTask, name="pulse.generate_report", soft_time_limit=240, time_limit=300)
def generate_report(self, report_type: str, params: dict) -> dict:
    if report_type not in {"daily", "weekly", "monthly", "quarterly", "yearly"}:
        raise PermanentError(f"Unknown report type '{report_type}'")
    for step in range(5):
        _simulate_work(1)
        log.info("[%s] report progress %d%%", self.request.id, (step + 1) * 20)
    report_id = random.randint(1000, 9999)
    return {
        "status": "completed",
        "report_type": report_type,
        "download_url": f"/reports/{report_type}_{report_id}.pdf",
        "size_bytes": random.randint(10_000, 500_000),
    }


@shared_task(bind=True, base=PulseTask, name="pulse.process_webhook")
def process_webhook(self, webhook_url: str, payload: dict) -> dict:
    log.info("[%s] delivering webhook to %s (attempt %d)", self.request.id, webhook_url, self.request.retries + 1)
    _simulate_work(1)
    if random.random() < SIMULATED_FAILURE_RATE["process_webhook"]:
        raise TransientError(f"{webhook_url} returned 503")
    return {"status": "delivered", "url": webhook_url, "response_code": 200}


SUPPORTED_OPERATIONS = {"resize", "compress", "crop", "grayscale", "thumbnail"}


@shared_task(bind=True, base=PulseTask, name="pulse.process_image", soft_time_limit=120, time_limit=150)
def process_image(self, image_url: str, operations: list) -> dict:
    unknown = set(operations) - SUPPORTED_OPERATIONS
    if unknown:
        raise PermanentError(f"Unsupported operations: {sorted(unknown)}")
    done = []
    try:
        for op in operations:
            _simulate_work(2)
            done.append(op)
    except SoftTimeLimitExceeded as exc:
        # Hitting the soft limit usually means the input is pathological; don't retry.
        raise PermanentError(f"Timed out after {len(done)}/{len(operations)} operations") from exc
    return {
        "status": "processed",
        "original_url": image_url,
        "processed_url": f"/processed/{random.randint(1000, 9999)}.jpg",
        "operations_applied": done,
    }
