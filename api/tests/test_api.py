import pytest

from app.celery_app import celery_app
from tests.conftest import API, EMAIL


@pytest.fixture
def published(monkeypatch):
    """Capture publishes instead of sending them (no worker in these tests)."""
    sent = []

    def fake_send_task(name, kwargs=None, queue=None, task_id=None, **_):
        sent.append({"name": name, "kwargs": kwargs, "queue": queue, "task_id": task_id})

    monkeypatch.setattr(celery_app, "send_task", fake_send_task)
    return sent


async def test_create_job_publishes_to_priority_queue(client, published):
    response = await client.post(f"{API}/", json={**EMAIL, "priority": "critical"})
    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "pending"
    assert job["max_retries"] == 3
    assert published == [
        {"name": "pulse.send_email", "kwargs": EMAIL["payload"], "queue": "critical", "task_id": job["celery_task_id"]}
    ]
    assert job["celery_task_id"].startswith(f"job-{job['id']}-")


async def test_idempotency_returns_original_job(client, published):
    body = {**EMAIL, "idempotency_key": "order-1-email"}
    first = await client.post(f"{API}/", json=body)
    second = await client.post(f"{API}/", json=body)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(published) == 1


async def test_unknown_task_is_400(client, published):
    response = await client.post(f"{API}/", json={"task_name": "mine_bitcoin", "payload": {}})
    assert response.status_code == 400
    assert published == []


@pytest.mark.parametrize(
    "payload",
    [
        {"to": "not-an-email", "subject": "s", "body": "b"},
        {"to": "a@example.com", "subject": "s"},
        {"to": "a@example.com", "subject": "s", "body": "b", "unexpected": 1},
    ],
)
async def test_payload_is_validated_per_task(client, published, payload):
    response = await client.post(f"{API}/", json={"task_name": "send_email", "payload": payload})
    assert response.status_code == 422
    assert published == []


async def test_broker_down_marks_job_failed_and_returns_503(client, monkeypatch):
    def broken(*args, **kwargs):
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(celery_app, "send_task", broken)
    response = await client.post(f"{API}/", json=EMAIL)
    assert response.status_code == 503

    jobs = (await client.get(f"{API}/")).json()["jobs"]
    assert jobs[0]["status"] == "failed"
    assert "redis unreachable" in jobs[0]["error_message"]


async def test_list_filters_and_pagination(client, published):
    for priority in ["low", "high", "high"]:
        await client.post(f"{API}/", json={**EMAIL, "priority": priority})
    high = (await client.get(f"{API}/", params={"priority": "high"})).json()
    assert high["total"] == 2
    page = (await client.get(f"{API}/", params={"page": 2, "page_size": 2})).json()
    assert page["total"] == 3 and len(page["jobs"]) == 1
    assert (await client.get(f"{API}/", params={"status": "completed"})).json()["total"] == 0


async def test_retry_only_allowed_for_failed_jobs(client, published):
    job = (await client.post(f"{API}/", json=EMAIL)).json()
    response = await client.post(f"{API}/{job['id']}/retry")
    assert response.status_code == 409


async def test_missing_job_is_404(client):
    assert (await client.get(f"{API}/12345")).status_code == 404


async def test_liveness(client):
    assert (await client.get("/health/live")).json() == {"status": "ok"}


async def test_readiness_reports_each_dependency(client):
    response = await client.get("/health")
    body = response.json()
    assert body["checks"]["database"] == "ok"
    # The test broker is in-memory, so the Redis ping fails and readiness is 503.
    assert body["checks"]["broker"].startswith("error")
    assert response.status_code == 503
