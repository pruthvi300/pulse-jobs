# Pulse — Design Notes

How Pulse is put together and why. For setup, see the [README](../README.md).

## 1. Overview

**Pulse** is a distributed job processing system that demonstrates enterprise-level patterns for reliable background task execution. It's designed to handle scenarios like:
- Sending transactional emails
- Generating reports
- Processing webhooks
- Image/video processing


## 2. Architecture Deep Dive

### 2.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    React Dashboard (Vite)                            │   │
│  │  - Real-time job status via polling                                  │   │
│  │  - Submit test jobs                                                  │   │
│  │  - Statistics visualization                                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ HTTP/REST
┌─────────────────────────────────────────────────────────────────────────────┐
│                          API LAYER                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    FastAPI (Async)                                   │   │
│  │  - POST /jobs/ - Create job with idempotency                         │   │
│  │  - GET /jobs/{id} - Get job status (syncs with Celery)              │   │
│  │  - GET /jobs/stats/summary - Dashboard metrics                       │   │
│  │  - POST /jobs/{id}/retry - Retry failed job                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                          │                    │
                          ▼                    ▼
┌────────────────────────────────┐   ┌────────────────────────────────────────┐
│        PERSISTENCE             │   │           MESSAGE BROKER               │
│  ┌────────────────────────┐    │   │  ┌────────────────────────────────┐   │
│  │     PostgreSQL         │    │   │  │         Redis                  │   │
│  │  - Jobs table          │    │   │  │  - Celery task queue           │   │
│  │  - Idempotency keys    │    │   │  │  - Result backend              │   │
│  │  - Audit trail         │    │   │  │  - Pub/Sub (future: WS)        │   │
│  └────────────────────────┘    │   │  └────────────────────────────────┘   │
└────────────────────────────────┘   └────────────────────────────────────────┘
                                                       │
                                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         WORKER LAYER                                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  Worker 1   │  │  Worker 2   │  │  Worker 3   │  │  Worker N   │        │
│  │  (Celery)   │  │  (Celery)   │  │  (Celery)   │  │  (Celery)   │        │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘        │
│                                                                              │
│  Tasks:                                                                      │
│  - send_email (5 retries, exponential backoff)                              │
│  - generate_report (2 retries, CPU-intensive)                               │
│  - process_webhook (10 retries, high reliability)                           │
│  - process_image (3 retries, time-limited)                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Request Flow

```
1. Client submits job via POST /api/v1/jobs/
   └─> { task_name: "send_email", payload: {...}, idempotency_key: "order-123-email" }

2. API Layer (FastAPI):
   a. Check idempotency_key in PostgreSQL
      └─> If exists: return existing job (no duplicate)
      └─> If not: continue
   b. Create Job record in PostgreSQL (status: PENDING)
   c. Send task to Redis via Celery send_task()
   d. Return Job response to client

3. Worker Layer (Celery):
   a. Worker picks up the task from its priority queue
   b. task_prerun signal  → job RUNNING, attempts = retries + 1
   c. Execute task (e.g., send email via SMTP)
   d. task_success signal → job COMPLETED with result
   e. TransientError:
      └─> retries left: task_retry signal → RETRYING, re-queued after backoff (full jitter)
      └─> none left:    task_failure signal → DEAD_LETTER with the last error
   f. PermanentError or unexpected exception → FAILED, no retry

4. Reading status:
   a. Client calls GET /jobs/{id} (or the dashboard polls the list)
   b. API reads PostgreSQL only — workers already keep it current,
      so nothing depends on Celery's expiring result backend
```

## 3. Key Technical Decisions

### 3.1 Why FastAPI over Flask?

| Aspect | Flask | FastAPI |
|--------|-------|---------|
| **Async** | Requires extensions (Quart) | Native async/await |
| **Type Hints** | Optional | Required (Pydantic) |
| **API Docs** | Requires Flask-Swagger | Auto-generated OpenAPI |
| **Performance** | Moderate | High (Starlette/Uvicorn) |
| **Modern** | Mature, older patterns | Modern, active development |

**Summary**: FastAPI was chosen because job submission and status polling are I/O-bound operations. FastAPI's native async support allows a single worker process to handle many concurrent connections efficiently.

### 3.2 Why Celery + Redis?

**Celery** is the de-facto standard for Python task queues:
- Mature (10+ years)
- Supports multiple brokers (Redis, RabbitMQ)
- Built-in retry mechanisms
- Monitoring (Flower)

**Redis** as broker:
- Fast in-memory storage
- Simple to operate
- Dual purpose: Queue + Result backend

### 3.3 Idempotency Pattern

**Problem**: Network failures can cause clients to retry submissions, creating duplicate jobs.

**Solution**: Client sends a unique `idempotency_key` (e.g., `order-123-confirmation-email`).

```python
# API checks for existing job with same key
existing = await db.execute(
    select(Job).where(Job.idempotency_key == idempotency_key)
)
if existing_job:
    return existing_job  # No duplicate created
```

**Summary**: Idempotency is critical for reliable distributed systems. By requiring clients to provide a unique key, we can safely retry failed requests without creating duplicate work.

### 3.4 Exponential Backoff

**Problem**: Immediate retries can overwhelm failing services.

**Solution**: Increase delay between retries exponentially.

```python
@shared_task(
    retry_backoff=True,        # Enable exponential backoff
    retry_backoff_max=600,     # Max 10 minutes between retries
    retry_jitter=True,         # Add randomness to prevent thundering herd
)
def send_email(...):
    ...
```

**Retry Schedule** (with jitter):
- Attempt 1: Immediate
- Attempt 2: ~60s delay
- Attempt 3: ~120s delay
- Attempt 4: ~240s delay
- Attempt 5: ~480s delay (capped at 600s)

## 4. Production Considerations

This demo omits some production concerns for simplicity:

| Feature | Current | Production Enhancement |
|---------|---------|------------------------|
| **Auth** | None | JWT/API Keys |
| **Rate Limiting** | None | Per-client limits via Redis |
| **Monitoring** | Flower | Prometheus + Grafana |
| **Logging** | stdout | ELK/Loki stack |
| **Deploy** | Docker Compose | Kubernetes with HPA (implemented in `k8s/`) |

## 5. Kubernetes Deployment

The project includes full Kubernetes manifests for production deployment in `k8s/`.

### Architecture on Kubernetes

```
┌──────────────┐     ┌──────────────────┐
│   Ingress    │────▶│   API (x2 pods)  │
│   (nginx)    │     │   FastAPI         │
└──────────────┘     └────────┬─────────┘
                              │
                      ┌───────▼────────┐
                      │     Redis      │
                      │  (StatefulSet) │
                      └───────┬────────┘
                              │
                   ┌──────────▼───────────┐
                   │  Workers (2-10 pods) │
                   │  Celery + HPA        │
                   │  (auto-scales)       │
                   └──────────┬───────────┘
                              │
                      ┌───────▼────────┐
                      │   PostgreSQL   │
                      │  (StatefulSet) │
                      └────────────────┘
```

### Manifest Files

| File | Purpose |
|------|---------|
| `k8s/namespace.yaml` | Isolated namespace for all Pulse resources |
| `k8s/config.yaml` | ConfigMap + Secrets for environment variables |
| `k8s/redis.yaml` | Redis StatefulSet with PersistentVolumeClaim |
| `k8s/postgres.yaml` | PostgreSQL StatefulSet with persistent storage |
| `k8s/api.yaml` | API Deployment (2 replicas) + ClusterIP Service + Ingress |
| `k8s/worker.yaml` | Worker Deployment + **HorizontalPodAutoscaler** (2→10 pods) |
| `k8s/flower.yaml` | Flower monitoring Deployment |

### Deploy

```bash
# Deploy all at once
kubectl apply -f k8s/

# Check pod status
kubectl get pods -n pulse

# Watch auto-scaler in action
kubectl get hpa -n pulse --watch

# View worker logs
kubectl logs -f deployment/pulse-worker -n pulse

# Access Flower monitoring
kubectl port-forward svc/pulse-flower 5555:5555 -n pulse
```

### Key Kubernetes Features Used

| Feature | Where | Why |
|---------|-------|---------|
| **HorizontalPodAutoscaler** | Workers | Auto-scale 2→10 pods at 70% CPU |
| **StatefulSet** | Redis, PostgreSQL | Stable network identity + persistent storage |
| **PersistentVolumeClaim** | Redis, PostgreSQL | Data survives pod restarts |
| **Readiness Probe** | API, Redis, PostgreSQL | Traffic only sent to healthy pods |
| **Liveness Probe** | API, Workers | Restart unresponsive pods automatically |
| **Ingress** | API | External access with path-based routing |
| **Secrets** | All services | Secure credential injection |
| **Resource Limits** | All pods | Prevent noisy neighbor issues |
