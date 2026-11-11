# Pulse — Async Job Processing Platform

[![CI](https://github.com/pruthvi300/pulse-jobs/actions/workflows/ci.yml/badge.svg)](https://github.com/pruthvi300/pulse-jobs/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-009688)
![Celery](https://img.shields.io/badge/Celery-5.3%2B-37814A)
![Redis](https://img.shields.io/badge/Redis-7%2B-DC382D)
![React](https://img.shields.io/badge/React-18%2B-61DAFB)
![Kubernetes](https://img.shields.io/badge/Kubernetes-HPA-326CE5)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

A distributed background job system built with **FastAPI**, **Celery**, **Redis**, **PostgreSQL** and a **React** dashboard. Clients submit jobs over a REST API; workers process them with retries, exponential backoff, idempotency keys and a dead-letter state, and every state change is recorded in PostgreSQL. It ships with Docker Compose for local use, Kubernetes manifests with autoscaling, Terraform for AWS, and a load test with measured results.

## 🏗 System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PULSE ARCHITECTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────┐        ┌─────────────┐        ┌─────────────┐             │
│   │  React UI   │───────▶│  FastAPI    │───────▶│   Redis     │             │
│   │ (Dashboard) │◀─poll──│   (REST)    │        │  (Broker)   │             │
│   └─────────────┘        └─────────────┘        └──────┬──────┘             │
│                                 │                      │                     │
│                                 ▼                      ▼                     │
│                          ┌───────────┐          ┌───────────┐               │
│                          │ PostgreSQL│          │  Celery   │               │
│                          │(Job state)│◀─signals─│  Workers  │               │
│                          └───────────┘          └───────────┘               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 🚀 Key Features

### Reliability Patterns
- **Idempotency Keys**: Prevent duplicate job execution using unique client-generated keys
- **Exponential Backoff**: Smart retry logic with configurable base delay and max attempts
- **Dead-letter state**: Jobs that exhaust their retries are marked `dead_letter` with the last error, and can be replayed
- **Transient vs permanent errors**: Only `TransientError` is retried; bad input fails fast as `failed`
- **Payload validation**: Each task has a Pydantic schema, so bad payloads are rejected at submission (422)
- **At-least-once delivery**: `acks_late` + `reject_on_worker_lost` redeliver tasks from crashed workers

### Scalability
- **Horizontal Scaling**: Spin up N workers with `docker-compose up --scale worker=5`
- **Priority Queues**: `critical`, `high`, `default`, `low` queues (run dedicated workers per queue for strict priority)

### Observability
- **Dashboard**: React UI polling every 3 seconds, with status filter and one-click retry
- **Job Status Tracking**: pending → running → (retrying) → completed / failed / dead_letter, written by workers via Celery signals
- **Health checks**: `/health/live` (liveness) and `/health` (PostgreSQL + Redis readiness)
- **Flower** for live worker and queue monitoring

### Load test
[`loadtest/`](loadtest/README.md) submits 5,000 jobs plus 500 duplicate submissions from 50
concurrent clients, with 30% of attempts failing, then checks every job. On one laptop
(one API process, one 8-process worker), it measured:

- 0 jobs lost or stuck, 0 duplicate jobs created
- 38 jobs dead-lettered, against ≈ 40.5 expected from the failure rate
- ~129 submissions/s (p95 1.06 s). The single API process is the bottleneck; the
  workers kept up with submissions.

## 🛠 Tech Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **API** | FastAPI | REST endpoints, async I/O |
| **Message Broker** | Redis | Job queues |
| **Task Workers** | Celery | Distributed task execution |
| **Database** | PostgreSQL | Job persistence, results storage |
| **Frontend** | React + Vite | Monitoring dashboard (polls every 3 s) |
| **Containerization** | Docker Compose | Local development |
| **Orchestration** | Kubernetes | Production deployment with HPA auto-scaling |
| **Infrastructure** | Terraform | AWS provisioning (VPC, ECS, RDS, ElastiCache) |

## ⚡️ Getting Started

### Prerequisites
- Docker and Docker Compose
- Python 3.11+ and Node.js 20+ (only for running tests or the dashboard outside Docker)

### Run with Docker (recommended)

```bash
git clone https://github.com/pruthvi300/pulse-jobs.git
cd pulse-jobs
docker compose up --build        # or: make dev-build
```

This starts the API, a Celery worker, Redis, PostgreSQL, Flower and the dashboard. Once it is up:

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:5173 |
| API docs (Swagger UI) | http://localhost:8000/docs |
| Flower (worker monitor) | http://localhost:5555 |
| Health check | http://localhost:8000/health |

### Submit a job

```bash
curl -X POST http://localhost:8000/api/v1/jobs/ \
  -H "Content-Type: application/json" \
  -d '{"task_name": "send_email", "payload": {"to": "a@example.com", "subject": "Hi", "body": "Hello"}, "idempotency_key": "demo-1"}'
```

Then watch it move through `pending → running → completed` on the dashboard, or with `GET /api/v1/jobs/{id}`. All endpoints are described in [docs/API_REFERENCE.md](docs/API_REFERENCE.md).

### Useful commands

```bash
make logs                 # follow all logs
make scale-workers N=5    # run more Celery workers
make queue-length         # jobs waiting in each queue
make stop                 # stop everything
```

### Run the tests

The test suite runs a real Celery worker on an in-memory broker with SQLite, so no Redis or PostgreSQL is needed.

```bash
cd api
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
pytest                    # or from the repo root: make test
ruff check app tests
```

## 📦 Project Structure

```
pulse_jobs/
├── api/                    # FastAPI Backend
│   ├── app/
│   │   ├── core/           # Settings, database engines
│   │   ├── models/         # SQLAlchemy Job model + state machine
│   │   ├── schemas/        # Pydantic DTOs and per-task payload schemas
│   │   ├── api/            # Route handlers
│   │   ├── tasks/          # base.py (retry policy), jobs.py (tasks), state.py (signals → DB), registry.py
│   │   └── celery_app.py   # Celery config (same image runs API and workers)
│   ├── tests/              # API tests + end-to-end tests with a real worker
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/               # React Dashboard
│   ├── src/
│   └── Dockerfile
├── docs/                   # Deep-dive documentation
├── k8s/                    # Kubernetes Manifests
│   ├── namespace.yaml      # Isolated namespace
│   ├── config.yaml         # ConfigMap + Secrets
│   ├── redis.yaml          # Redis StatefulSet
│   ├── postgres.yaml       # PostgreSQL StatefulSet
│   ├── api.yaml            # API Deployment + Ingress
│   ├── worker.yaml         # Worker Deployment + HPA (2→10 pods)
│   └── flower.yaml         # Monitoring Deployment
├── terraform/              # Infrastructure as Code (AWS)
│   ├── main.tf             # Provider + backend config
│   ├── variables.tf        # Input variables
│   ├── vpc.tf              # VPC, subnets, security groups
│   ├── ecs.tf              # ECS Fargate + auto-scaling
│   ├── rds.tf              # RDS PostgreSQL
│   ├── elasticache.tf      # ElastiCache Redis
│   └── outputs.tf          # Resource endpoints
└── docker-compose.yml      # Local orchestration
```

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/GETTING_STARTED.md) | Detailed local setup and troubleshooting |
| [Design Notes](docs/DESIGN.md) | Architecture, data model and key decisions |
| [Reliability Patterns](docs/RELIABILITY_PATTERNS.md) | Idempotency, backoff, dead-letter handling, timeouts |
| [API Reference](docs/API_REFERENCE.md) | All endpoints with examples |
| [Testing](docs/TESTING.md) | How the test suite is organised |
| [Deployment](docs/DEPLOYMENT.md) | Docker Compose, AWS ECS (Terraform), Kubernetes |
| [Load Test](loadtest/README.md) | Method and results of the 5,000-job load test |

## License

[MIT](LICENSE)
