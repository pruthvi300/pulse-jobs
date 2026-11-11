# Reliability Patterns: Building Bulletproof Systems

## Overview

Distributed systems fail. Networks drop. Services timeout. The question isn't *if* something will fail, but *when* and *how you handle it*.

This document covers the key reliability patterns implemented in Pulse.

---

## 1. Idempotency

### What is Idempotency?

An operation is **idempotent** if performing it multiple times has the same effect as performing it once.

```
Idempotent:     GET /user/123          (fetching doesn't change state)
Idempotent:     PUT /user/123 {data}   (updating to same state)
NOT Idempotent: POST /charge {$100}    (charges $100 each time!)
```

### Why It Matters for Job Queues

**Scenario:** User clicks "Send Invoice" button. Network timeout. User clicks again.

❌ **Without Idempotency:**
```
Request 1: Create job → Send invoice → Success (but network timed out)
Request 2: Create job → Send invoice → Success
Result: Customer receives 2 invoices!
```

✅ **With Idempotency:**
```
Request 1: Create job (key: "invoice-order-123") → Send invoice → Success
Request 2: Find existing job with key "invoice-order-123" → Return existing
Result: Customer receives 1 invoice
```

### Implementation in Pulse

```python
# In app/api/v1/jobs.py

@router.post("/", response_model=JobResponse)
async def create_job(job_in: JobCreate, db: AsyncSession = Depends(get_db)):
    # Step 1: Check if job with this idempotency key already exists
    if job_in.idempotency_key:
        existing = await db.execute(
            select(Job).where(Job.idempotency_key == job_in.idempotency_key)
        )
        existing_job = existing.scalar_one_or_none()
        if existing_job:
            # Return existing job - no duplicate created!
            return existing_job
    
    # Step 2: Create new job only if no duplicate found
    job = Job(...)
    db.add(job)
    await db.commit()
    ...
```

### Best Practices

1. **Client generates the key**: The client knows the business context (e.g., order ID)
2. **Keys should be meaningful**: `order-123-invoice` not `random-uuid`
3. **Keys should have TTL**: Store idempotency keys for 24-48 hours, then allow re-submission

---

## 2. Retry with Exponential Backoff

### The Problem with Immediate Retries

If a service is down, hammering it with retries makes things worse:

```
Service down at T=0
  Retry at T=1s
  Retry at T=2s
  Retry at T=3s
  ...
Result: Service is overwhelmed, stays down longer
```

### Exponential Backoff

Increase delay between retries exponentially:

```
Attempt 1: Immediate
Attempt 2: Wait 2 seconds
Attempt 3: Wait 4 seconds
Attempt 4: Wait 8 seconds
Attempt 5: Wait 16 seconds (capped at max)
```

Formula: `delay = min(base * 2^attempt, max_delay)`

### Implementation in Pulse

```python
# In app/tasks/jobs.py

@shared_task(
    bind=True,
    max_retries=5,
    default_retry_delay=60,           # Base delay: 60 seconds
    retry_backoff=True,               # Enable exponential backoff
    retry_backoff_max=600,            # Max delay: 10 minutes
    retry_jitter=True,                # Add randomness
)
def send_email(self, to: str, subject: str, body: str):
    try:
        send_via_smtp(to, subject, body)
    except SMTPError as e:
        # Celery automatically retries with backoff
        raise
```

### Jitter: Preventing Thundering Herd

**Problem:** If 1000 tasks fail at the same time, they all retry at the same time.

**Solution:** Add random "jitter" to spread out retries.

```python
retry_jitter=True  # Celery picks a random delay between 0 and the backoff value (full jitter)
```

Without jitter:
```
Task 1 retries at: T+60s
Task 2 retries at: T+60s
Task 3 retries at: T+60s
... (all hit the service at once)
```

With jitter:
```
Task 1 retries at: T+52s
Task 2 retries at: T+67s
Task 3 retries at: T+58s
... (spread out, service can recover)
```

---

## 3. Dead Letter Queue (DLQ)

### What is a DLQ?

A Dead Letter Queue is a separate queue where failed messages go after exhausting all retries.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Main Queue │────▶│   Worker    │────▶│   Success   │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                           ▼ (after max retries)
                    ┌─────────────┐
                    │  Dead Letter│
                    │    Queue    │
                    └─────────────┘
```

### Why DLQ Matters

1. **Failed jobs aren't lost**: They're preserved for analysis
2. **Production stays clean**: Main queue isn't clogged with poison messages
3. **Debugging**: Full context (payload, error, attempts) is preserved
4. **Manual replay**: Ops can retry after fixing the root cause

### Implementation in Pulse

```python
# In app/models/job.py

class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD_LETTER = "dead_letter"  # Failed after all retries
```

```python
# In app/api/v1/jobs.py

@router.post("/{job_id}/retry")
async def retry_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """
    Retry a job that's in the Dead Letter Queue.
    Only jobs in FAILED or DEAD_LETTER status can be retried.
    """
    job = await get_job_or_404(job_id, db)
    
    if job.status not in [JobStatus.FAILED, JobStatus.DEAD_LETTER]:
        raise HTTPException(400, "Only failed jobs can be retried")
    
    # Reset and re-queue
    job.status = JobStatus.PENDING
    job.error_message = None
    # ... re-submit to Celery
```

---

## 4. Circuit Breaker (Conceptual)

### The Pattern

A circuit breaker prevents calling a failing service repeatedly.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CIRCUIT BREAKER STATES                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────┐          failures > threshold          ┌─────────┐            │
│  │ CLOSED  │ ───────────────────────────────────▶  │  OPEN   │            │
│  │ (allow) │                                        │ (block) │            │
│  └─────────┘                                        └────┬────┘            │
│       ▲                                                  │                 │
│       │                                                  │ timeout         │
│       │                   success                        ▼                 │
│       │ ◀───────────────────────────────────────── ┌──────────┐           │
│       │                                            │HALF-OPEN │           │
│       │ ◀────────────── failure ───────────────── │  (test)  │           │
│                                                    └──────────┘           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### States Explained

| State | Behavior |
|-------|----------|
| **CLOSED** | Normal operation, requests flow through |
| **OPEN** | Service is down, fail fast without calling |
| **HALF-OPEN** | Allow one test request to check if service recovered |

### Why It Matters

Without circuit breaker:
```
Service A → Service B (down)
           └─ Timeout after 30s
           └─ Retry → Timeout after 30s
           └─ Retry → Timeout after 30s
Result: Each request takes 90s, system grinds to a halt
```

With circuit breaker:
```
Service A → Circuit Breaker → Service B (down)
           └─ After 5 failures, circuit OPENS
           └─ Next 100 requests: Fail fast (1ms each)
           └─ After 60s: Try one request (HALF-OPEN)
           └─ If success: Circuit CLOSES
Result: Fast failure, system stays responsive
```

### Implementation Note

This project doesn't implement a full circuit breaker, but it is a natural next step:

```python
# Conceptual implementation with pybreaker
from pybreaker import CircuitBreaker

breaker = CircuitBreaker(fail_max=5, reset_timeout=60)

@breaker
def call_external_service(data):
    return requests.post("https://api.external.com", json=data)
```

---

## 5. Timeout Management

### Why Timeouts Matter

Without timeouts, a slow service can:
1. Hold up workers indefinitely
2. Exhaust connection pools
3. Cause cascading failures

### Implementation in Celery

```python
@shared_task(
    time_limit=300,       # Hard kill after 5 minutes
    soft_time_limit=240,  # Raise exception after 4 minutes (graceful)
)
def process_image(image_url: str):
    try:
        # Long-running task
        process(image_url)
    except SoftTimeLimitExceeded:
        # Graceful shutdown: save progress, clean up
        save_partial_result()
        raise
```

### Time Limit vs Soft Time Limit

| Type | Behavior |
|------|----------|
| **soft_time_limit** | Raises `SoftTimeLimitExceeded` - can be caught |
| **time_limit** | Kills the process immediately - cannot be caught |

Always set `soft_time_limit` slightly below `time_limit` to allow cleanup.
