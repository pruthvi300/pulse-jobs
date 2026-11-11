from app.core.config import settings
from app.tasks.base import backoff_delay, job_id_from_task_id


def test_backoff_is_capped_and_jittered(monkeypatch):
    monkeypatch.setattr(settings, "RETRY_BACKOFF_BASE_SECONDS", 30.0)
    monkeypatch.setattr(settings, "RETRY_BACKOFF_MAX_SECONDS", 600.0)
    for retries, cap in [(0, 30), (1, 60), (3, 240), (10, 600)]:
        delays = [backoff_delay(retries) for _ in range(200)]
        assert all(0 <= d <= cap for d in delays)
        assert max(delays) > cap * 0.5  # spread across the range, not a fixed value


def test_job_id_parsing():
    assert job_id_from_task_id("job-42-abc123") == 42
    assert job_id_from_task_id("something-else") is None
    assert job_id_from_task_id(None) is None
