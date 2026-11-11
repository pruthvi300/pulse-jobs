# Testing Guide

> **What the suite in `api/tests/` does today:**
> - `test_api.py` — API behaviour with publishing stubbed out (validation, idempotency, 503 on broker failure, filters, health).
> - `test_end_to_end.py` — starts a **real Celery worker thread** (`celery.contrib.testing.worker.start_worker`) on the in-memory broker and a SQLite file, then checks completed, retried-then-succeeded, dead-lettered, failed, and replayed jobs.
> - `test_retry_policy.py` — backoff bounds and task-id parsing.
>
> Run with `cd api && pytest`. No Redis or PostgreSQL needed. The examples below are general techniques.

## Overview

This guide covers testing strategies for the Pulse job processing system. We use **pytest** with async support for testing FastAPI endpoints and Celery tasks.

---

## Test Structure

```
pulse_jobs/
├── api/
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py          # Shared fixtures
│       ├── test_api/
│       │   ├── __init__.py
│       │   └── test_jobs.py     # API endpoint tests
│       └── test_tasks/
│           ├── __init__.py
│           └── test_jobs.py     # Celery task tests
```

---

## Testing Philosophy

### The Testing Pyramid

```
        /\
       /  \      E2E Tests (Few)
      /----\     - Full system integration
     /      \    - Slow, flaky
    /--------\   Integration Tests (Some)
   /          \  - API endpoints + DB
  /------------\ - Medium speed
 /              \ Unit Tests (Many)
/----------------\ - Individual functions
                   - Fast, reliable
```

For Pulse, we focus on:
1. **Unit Tests**: Task logic, utility functions
2. **Integration Tests**: API endpoints with test database
3. **E2E Tests**: Full flow with Docker Compose (manual/CI)

---

## Setting Up Tests

### 1. Install Test Dependencies

The test dependencies are already in `requirements.txt`:

```
pytest==7.4.4
pytest-asyncio==0.23.3
httpx==0.26.0
```

### 2. Create conftest.py

```python
# api/tests/conftest.py
"""
Pytest fixtures for testing.

Fixtures are reusable test components:
- Database sessions
- HTTP clients
- Mock data
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models.job import Base
from app.core.database import get_db


# Use in-memory SQLite for fast, isolated tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Create test engine
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
)

# Create test session factory
TestSessionLocal = sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest_asyncio.fixture
async def db_session():
    """
    Create a fresh database for each test.
    
    Workflow:
    1. Create all tables
    2. Yield session for test to use
    3. Drop all tables (cleanup)
    
    This ensures tests are isolated - one test's data
    doesn't affect another.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with TestSessionLocal() as session:
        yield session
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session):
    """
    HTTP client for testing API endpoints.
    
    Uses HTTPX's AsyncClient with ASGITransport to call
    FastAPI directly (no network, faster tests).
    
    The get_db dependency is overridden to use our test database.
    """
    
    async def override_get_db():
        yield db_session
    
    # Override the dependency
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client
    
    # Clear overrides after test
    app.dependency_overrides.clear()


@pytest.fixture
def sample_job_payload():
    """Sample payload for creating a job."""
    return {
        "task_name": "send_email",
        "payload": {
            "to": "test@example.com",
            "subject": "Test Email",
            "body": "Hello from tests!"
        },
        "priority": "default",
        "idempotency_key": "test-key-123"
    }
```

---

## Writing API Tests

### Test Job Creation

```python
# api/tests/test_api/test_jobs.py
"""
API endpoint tests for /jobs routes.

These are INTEGRATION tests - they test the full request/response
cycle including database operations.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_job(client: AsyncClient, sample_job_payload):
    """
    Test: Creating a job returns 201 and job data.
    
    Verifies:
    - Status code is 201 Created
    - Response contains job ID
    - Status starts as 'pending'
    """
    response = await client.post(
        "/api/v1/jobs/",
        json=sample_job_payload
    )
    
    assert response.status_code == 201
    data = response.json()
    
    assert "id" in data
    assert data["task_name"] == "send_email"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_create_job_idempotency(client: AsyncClient, sample_job_payload):
    """
    Test: Submitting the same idempotency_key returns existing job.
    
    This is a critical reliability feature - network retries
    shouldn't create duplicate jobs.
    """
    # First submission
    response1 = await client.post("/api/v1/jobs/", json=sample_job_payload)
    assert response1.status_code == 201
    job1 = response1.json()
    
    # Second submission with SAME idempotency_key
    response2 = await client.post("/api/v1/jobs/", json=sample_job_payload)
    assert response2.status_code == 201
    job2 = response2.json()
    
    # Should return the SAME job, not create a new one
    assert job1["id"] == job2["id"]


@pytest.mark.asyncio
async def test_create_job_invalid_task(client: AsyncClient):
    """
    Test: Unknown task name returns 400 Bad Request.
    """
    response = await client.post(
        "/api/v1/jobs/",
        json={
            "task_name": "invalid_task_name",
            "payload": {}
        }
    )
    
    assert response.status_code == 400
    assert "Unknown task" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_job(client: AsyncClient, sample_job_payload):
    """
    Test: GET /jobs/{id} returns job details.
    """
    # Create a job first
    create_response = await client.post("/api/v1/jobs/", json=sample_job_payload)
    job_id = create_response.json()["id"]
    
    # Get the job
    response = await client.get(f"/api/v1/jobs/{job_id}")
    
    assert response.status_code == 200
    assert response.json()["id"] == job_id


@pytest.mark.asyncio
async def test_get_job_not_found(client: AsyncClient):
    """
    Test: GET /jobs/{id} with invalid ID returns 404.
    """
    response = await client.get("/api/v1/jobs/99999")
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_jobs(client: AsyncClient, sample_job_payload):
    """
    Test: GET /jobs/ returns paginated list.
    """
    # Create multiple jobs
    for i in range(5):
        payload = sample_job_payload.copy()
        payload["idempotency_key"] = f"test-key-{i}"
        await client.post("/api/v1/jobs/", json=payload)
    
    # List jobs
    response = await client.get("/api/v1/jobs/")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["total"] == 5
    assert len(data["jobs"]) == 5


@pytest.mark.asyncio
async def test_list_jobs_with_filter(client: AsyncClient, sample_job_payload):
    """
    Test: GET /jobs/?status=pending filters correctly.
    """
    # Create a job
    await client.post("/api/v1/jobs/", json=sample_job_payload)
    
    # Filter by status
    response = await client.get("/api/v1/jobs/?status=pending")
    
    assert response.status_code == 200
    for job in response.json()["jobs"]:
        assert job["status"] == "pending"


@pytest.mark.asyncio
async def test_get_stats(client: AsyncClient, sample_job_payload):
    """
    Test: GET /jobs/stats/summary returns counts.
    """
    # Create some jobs
    for i in range(3):
        payload = sample_job_payload.copy()
        payload["idempotency_key"] = f"stats-key-{i}"
        await client.post("/api/v1/jobs/", json=payload)
    
    response = await client.get("/api/v1/jobs/stats/summary")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["total_jobs"] == 3
    assert data["pending"] == 3
```

---

## Writing Task Tests

### Test Celery Tasks

```python
# api/tests/test_tasks/test_jobs.py
"""
Unit tests for Celery tasks.

These test the task LOGIC without actually running Celery.
We call the task function directly.
"""

import pytest
from unittest.mock import patch, MagicMock


def test_send_email_success():
    """
    Test: send_email returns success on happy path.
    
    We mock random.random() to always return 1.0 (no failure).
    """
    from app.tasks.jobs import send_email
    
    # Mock to prevent random failures
    with patch('app.tasks.jobs.random.random', return_value=1.0):
        with patch('app.tasks.jobs.time.sleep'):  # Skip delays
            result = send_email(
                to="test@example.com",
                subject="Test",
                body="Hello"
            )
    
    assert result["status"] == "sent"
    assert result["recipient"] == "test@example.com"
    assert "message_id" in result


def test_send_email_failure():
    """
    Test: send_email raises exception on SMTP failure.
    
    We mock random.random() to return 0.1 (triggers failure).
    """
    from app.tasks.jobs import send_email
    
    with patch('app.tasks.jobs.random.random', return_value=0.1):
        with pytest.raises(Exception) as exc_info:
            send_email(to="test@example.com", subject="Test", body="Hello")
    
    assert "SMTP server temporarily unavailable" in str(exc_info.value)


def test_generate_report():
    """
    Test: generate_report completes successfully.
    """
    from app.tasks.jobs import generate_report
    
    with patch('app.tasks.jobs.time.sleep'):  # Skip delays
        result = generate_report(
            report_type="monthly",
            params={"month": "January"}
        )
    
    assert result["status"] == "completed"
    assert result["report_type"] == "monthly"
    assert "download_url" in result
```

---

## Running Tests

### Run All Tests

```bash
cd pulse_jobs/api
pytest -v
```

### Run Specific Test File

```bash
pytest tests/test_api/test_jobs.py -v
```

### Run with Coverage

```bash
pytest --cov=app --cov-report=html
# Open htmlcov/index.html in browser
```

### Run Only Async Tests

```bash
pytest -v -m asyncio
```

---

## Testing Best Practices

### 1. Arrange, Act, Assert (AAA)

```python
async def test_example(client):
    # ARRANGE - Set up test data
    payload = {"task_name": "send_email", ...}
    
    # ACT - Perform the action
    response = await client.post("/api/v1/jobs/", json=payload)
    
    # ASSERT - Verify the result
    assert response.status_code == 201
```

### 2. One Assertion Per Test (When Possible)

```python
# Good: Focused test
async def test_job_returns_201(client, payload):
    response = await client.post("/api/v1/jobs/", json=payload)
    assert response.status_code == 201

# Also Good: Multiple related assertions
async def test_job_response_structure(client, payload):
    response = await client.post("/api/v1/jobs/", json=payload)
    data = response.json()
    
    assert "id" in data
    assert "status" in data
    assert "created_at" in data
```

### 3. Use Fixtures for Repeated Setup

```python
# conftest.py
@pytest.fixture
def sample_email_payload():
    return {"to": "test@example.com", "subject": "Test", "body": "Hello"}

# test_jobs.py
async def test_email_job(client, sample_email_payload):
    response = await client.post("/api/v1/jobs/", json={
        "task_name": "send_email",
        "payload": sample_email_payload
    })
```

### 4. Test Edge Cases

```python
async def test_empty_payload(client):
    """Job with no payload should work."""
    response = await client.post("/api/v1/jobs/", json={
        "task_name": "send_email",
        "payload": None
    })
    assert response.status_code == 201

async def test_very_long_idempotency_key(client):
    """Keys near the limit should work."""
    response = await client.post("/api/v1/jobs/", json={
        "task_name": "send_email",
        "idempotency_key": "a" * 255
    })
    assert response.status_code == 201
```

---

## Mocking External Services

### Mock Celery Task Submission

For integration tests, you might want to mock Celery to avoid actually queueing tasks:

```python
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_job_without_celery(client, sample_job_payload):
    """Test job creation without actually sending to Celery."""
    
    mock_result = MagicMock()
    mock_result.id = "mock-task-id"
    
    with patch('app.api.v1.jobs.celery_app.send_task', return_value=mock_result):
        response = await client.post("/api/v1/jobs/", json=sample_job_payload)
    
    assert response.status_code == 201
    assert response.json()["celery_task_id"] == "mock-task-id"
```

---

## CI/CD Integration

### GitHub Actions Example

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          cd api
          pip install -r requirements.txt
      
      - name: Run tests
        run: |
          cd api
          pytest -v --cov=app --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```
