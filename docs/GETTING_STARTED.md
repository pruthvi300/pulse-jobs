# Getting Started: Running Pulse Locally

## Prerequisites

Before starting, ensure you have installed:

- **Docker Desktop** (includes Docker Compose)
  - macOS/Windows: [Download Docker Desktop](https://www.docker.com/products/docker-desktop/)
  - Linux: [Install Docker Engine](https://docs.docker.com/engine/install/)
  
- **Git** (to clone the repository)

Optional (for frontend development):
- **Node.js 18+** (for running frontend outside Docker)

---

## Quick Start (5 minutes)

### 1. Clone the Repository

```bash
git clone https://github.com/pruthvi300/pulse-jobs.git
cd pulse-jobs
```

### 2. Start All Services

```bash
docker compose up --build
```

This command:
1. Builds Docker images for API, Worker, and Frontend
2. Pulls Redis and PostgreSQL images
3. Creates a Docker network for inter-service communication
4. Starts all 6 services

**First run takes 2-5 minutes** (downloading images, installing dependencies).

### 3. Access the Application

Once you see logs like `Pulse API started`, open:

| Service | URL | Description |
|---------|-----|-------------|
| **API Docs** | http://localhost:8000/docs | Swagger UI for testing API |
| **Dashboard** | http://localhost:5173 | React UI frontend |
| **Flower** | http://localhost:5555 | Celery task monitor |

---

## Testing the System

### Via Dashboard (Easiest)

1. Open http://localhost:5173
2. Click "Send Email" or any task button
3. Watch the job appear in the table
4. Status updates every 5 seconds

### Via API (Swagger UI)

1. Open http://localhost:8000/docs
2. Find `POST /api/v1/jobs/`
3. Click "Try it out"
4. Use this sample payload:

```json
{
  "task_name": "send_email",
  "payload": {
    "to": "test@example.com",
    "subject": "Hello from Pulse!",
    "body": "This is a test email."
  },
  "priority": "default",
  "idempotency_key": "test-email-001"
}
```

5. Click "Execute"
6. Copy the returned `id`
7. Use `GET /api/v1/jobs/{id}` to check status

### Via Command Line (cURL)

```bash
# Create a job
curl -X POST http://localhost:8000/api/v1/jobs/ \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "send_email",
    "payload": {
      "to": "user@example.com",
      "subject": "Test",
      "body": "Hello!"
    }
  }'

# Check job status
curl http://localhost:8000/api/v1/jobs/1

# List all jobs
curl http://localhost:8000/api/v1/jobs/

# Get statistics
curl http://localhost:8000/api/v1/jobs/stats/summary
```

---

## Viewing Logs

### All Services
```bash
docker-compose logs -f
```

### Specific Service
```bash
# API logs
docker-compose logs -f api

# Worker logs (see task execution)
docker-compose logs -f worker

# Database logs
docker-compose logs -f postgres
```

---

## Scaling Workers

To process more jobs concurrently, scale the worker service:

```bash
# Run 5 worker instances
docker-compose up --scale worker=5
```

Each worker runs 2 concurrent tasks (configurable), so 5 workers = 10 concurrent jobs.

---

## Stopping the Application

```bash
# Stop all services
docker-compose down

# Stop and remove volumes (resets database!)
docker-compose down -v
```

---

## Common Issues

### Port Already in Use

```
Error: Bind for 0.0.0.0:8000 failed: port is already allocated
```

**Solution:** Another service is using port 8000. Either:
1. Stop the conflicting service
2. Change the port in `docker-compose.yml`

### Database Connection Failed

```
Connection refused: postgres:5432
```

**Solution:** PostgreSQL isn't ready yet. Wait a few seconds and retry, or restart:
```bash
docker-compose restart api worker
```

### Frontend Not Loading

**Check if API is running:**
```bash
curl http://localhost:8000/
```

**Check browser console** for CORS errors.

### Worker Not Processing Jobs

**Check worker logs:**
```bash
docker-compose logs -f worker
```

**Verify Redis is running:**
```bash
docker-compose exec redis redis-cli PING
# Should return: PONG
```

---

## Development Workflow

### Making Code Changes

The `docker-compose.yml` mounts local code as volumes:
- API code changes: Auto-reload (uvicorn --reload)
- Worker code changes: Need restart (`docker-compose restart worker`)
- Frontend changes: Auto-reload (Vite HMR)

### Running Commands Inside Containers

```bash
# Open shell in API container
docker-compose exec api bash

# Run Python commands
docker-compose exec api python -c "from app.core.config import settings; print(settings)"

# Run database migrations (when added)
# Tables are created automatically when the API starts (no migrations yet)
```

### Resetting Everything

```bash
# Stop all, remove containers and volumes
docker-compose down -v

# Rebuild from scratch
docker-compose up --build
```

---

## Next Steps

1. **Explore the code**: Start with `api/app/main.py`
2. **Read the docs**: See `docs/` folder for deep dives
3. **Add a new task**: Create a function in `api/app/tasks/jobs.py`
4. **Add tests**: See `tests/` folder structure
