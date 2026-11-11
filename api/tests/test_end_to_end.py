"""API → in-memory broker → real worker thread → signals → database."""

import itertools

import app.tasks.jobs as jobs
from tests.conftest import API, EMAIL, wait_for_terminal


async def test_job_completes(client, worker):
    job = (await client.post(f"{API}/", json=EMAIL)).json()
    done = await wait_for_terminal(client, job["id"])
    assert done["status"] == "completed"
    assert done["attempts"] == 1
    assert done["result"]["recipient"] == "a@example.com"
    assert done["started_at"] and done["completed_at"]


async def test_transient_failures_are_retried_then_succeed(client, worker, monkeypatch):
    rolls = itertools.chain([0.0, 0.0], itertools.repeat(0.99))  # fail, fail, then succeed

    class FlakyRandom:
        random = staticmethod(lambda: next(rolls))
        randint = staticmethod(lambda a, b: a)

    monkeypatch.setattr(jobs, "random", FlakyRandom)
    monkeypatch.setitem(jobs.SIMULATED_FAILURE_RATE, "send_email", 0.5)

    job = (await client.post(f"{API}/", json=EMAIL)).json()
    done = await wait_for_terminal(client, job["id"])
    assert done["status"] == "completed"
    assert done["attempts"] == 3


async def test_exhausted_retries_go_to_dead_letter(client, worker, monkeypatch):
    monkeypatch.setitem(jobs.SIMULATED_FAILURE_RATE, "send_email", 1.0)
    job = (await client.post(f"{API}/", json={**EMAIL, "max_retries": 2})).json()
    done = await wait_for_terminal(client, job["id"])
    assert done["status"] == "dead_letter"
    assert done["attempts"] == 3  # first try + 2 retries
    assert "Gave up after 3 attempts" in done["error_message"]


async def test_permanent_error_is_not_retried(client, worker):
    body = {"task_name": "generate_report", "payload": {"report_type": "bogus", "params": {}}}
    job = (await client.post(f"{API}/", json=body)).json()
    done = await wait_for_terminal(client, job["id"])
    assert done["status"] == "failed"
    assert done["attempts"] == 1
    assert "Unknown report type" in done["error_message"]


async def test_manual_retry_of_dead_letter_job(client, worker, monkeypatch):
    monkeypatch.setitem(jobs.SIMULATED_FAILURE_RATE, "send_email", 1.0)
    job = (await client.post(f"{API}/", json={**EMAIL, "max_retries": 0})).json()
    assert (await wait_for_terminal(client, job["id"]))["status"] == "dead_letter"

    monkeypatch.setitem(jobs.SIMULATED_FAILURE_RATE, "send_email", 0.0)
    retried = (await client.post(f"{API}/{job['id']}/retry")).json()
    assert retried["status"] == "pending"
    assert retried["celery_task_id"] != job["celery_task_id"]
    done = await wait_for_terminal(client, job["id"])
    assert done["status"] == "completed"
    assert done["attempts"] == 1


async def test_stats_count_every_status(client, worker, monkeypatch):
    await wait_for_terminal(client, (await client.post(f"{API}/", json=EMAIL)).json()["id"])
    bad = {"task_name": "process_image", "payload": {"image_url": "https://x.io/a.png", "operations": ["explode"]}}
    await wait_for_terminal(client, (await client.post(f"{API}/", json=bad)).json()["id"])

    stats = (await client.get(f"{API}/stats/summary")).json()
    assert stats == {
        "total_jobs": 2,
        "pending": 0,
        "running": 0,
        "retrying": 0,
        "completed": 1,
        "failed": 1,
        "dead_letter": 0,
    }
