import os
import tempfile

_db_file = os.path.join(tempfile.mkdtemp(prefix="pulse-test-"), "pulse.db")
os.environ.update(
    DATABASE_URL=f"sqlite+aiosqlite:///{_db_file}",
    CELERY_BROKER_URL="memory://",
    CELERY_RESULT_BACKEND="cache+memory://",
    RETRY_BACKOFF_BASE_SECONDS="0.01",
    RETRY_BACKOFF_MAX_SECONDS="0.05",
    DEFAULT_MAX_RETRIES="3",
)

import asyncio  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from celery.contrib.testing.worker import start_worker  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

import app.tasks.jobs as jobs  # noqa: E402
from app.celery_app import celery_app  # noqa: E402
from app.core.database import sync_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.models.job import Base, Job  # noqa: E402

API = "/api/v1/jobs"
TERMINAL = {"completed", "failed", "dead_letter"}


@pytest.fixture(scope="session", autouse=True)
def database():
    engine = sync_session_factory().kw["bind"]
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def clean_tables_and_fast_tasks(monkeypatch):
    with sync_session_factory()() as session:
        session.execute(delete(Job))
        session.commit()
    monkeypatch.setattr(jobs, "SIMULATED_LATENCY_SECONDS", 0)
    monkeypatch.setitem(jobs.SIMULATED_FAILURE_RATE, "send_email", 0.0)
    monkeypatch.setitem(jobs.SIMULATED_FAILURE_RATE, "process_webhook", 0.0)


@pytest.fixture(scope="session")
def worker():
    """A real Celery worker thread consuming the in-memory broker."""
    with start_worker(celery_app, perform_ping_check=False, shutdown_timeout=10):
        yield


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def wait_for_terminal(client, job_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = (await client.get(f"{API}/{job_id}")).json()
        if job["status"] in TERMINAL:
            return job
        await asyncio.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {job}")


EMAIL = {"task_name": "send_email", "payload": {"to": "a@example.com", "subject": "Hi", "body": "Hello"}}
