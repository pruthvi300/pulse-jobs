# Deployment Guide

## Overview

This guide covers deploying Pulse to production environments, from simple single-server setups to cloud-native Kubernetes deployments.

---

## Deployment Options

| Option | Complexity | Use Case |
|--------|------------|----------|
| Docker Compose | Low | Small scale, single server |
| AWS ECS | Medium | Medium scale, managed containers |
| Kubernetes | High | Large scale, multi-region |

---

## Pre-Deployment Checklist

Before deploying to production, ensure:

- [ ] All tests pass (`pytest -v`)
- [ ] Environment variables configured
- [ ] Secrets stored securely (not in code)
- [ ] Database migrations ready
- [ ] Monitoring/alerting configured
- [ ] Backup strategy in place
- [ ] SSL/TLS certificates obtained

---

## Option 1: Docker Compose (Single Server)

Best for: Small teams, MVPs, internal tools.

### 1. Prepare Production Compose File

Create `docker-compose.prod.yml`:

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data
    restart: always

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: always

  api:
    build:
      context: ./api
      dockerfile: Dockerfile.prod
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - CELERY_BROKER_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - CELERY_RESULT_BACKEND=redis://:${REDIS_PASSWORD}@redis:6379/1
      - DEBUG=false
    depends_on:
      - redis
      - postgres
    restart: always
    # Run with multiple Uvicorn workers
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

  worker:
    build:
      context: ./api
      dockerfile: Dockerfile.prod
    environment:
      - DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      - CELERY_BROKER_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - CELERY_RESULT_BACKEND=redis://:${REDIS_PASSWORD}@redis:6379/1
    depends_on:
      - redis
      - postgres
    restart: always
    command: celery -A app.celery_app worker --loglevel=info --concurrency=4
    # Scale with: docker-compose up --scale worker=5

  flower:
    build:
      context: ./api
      dockerfile: Dockerfile.prod
    ports:
      - "5555:5555"
    environment:
      - CELERY_BROKER_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - FLOWER_BASIC_AUTH=${FLOWER_USER}:${FLOWER_PASSWORD}
    depends_on:
      - redis
    restart: always
    command: celery -A app.celery_app flower --port=5555

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - /etc/letsencrypt:/etc/letsencrypt
    depends_on:
      - api
    restart: always

volumes:
  redis_data:
  postgres_data:
```

### 2. Create Production Dockerfile

Create `api/Dockerfile.prod`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create non-root user for security
RUN adduser --disabled-password --gecos '' appuser
USER appuser

# No CMD - specified in docker-compose
```

### 3. Configure Nginx

Create `nginx.conf`:

```nginx
events {
    worker_connections 1024;
}

http {
    upstream api {
        server api:8000;
    }

    server {
        listen 80;
        server_name pulse.yourdomain.com;

        # Redirect HTTP to HTTPS
        return 301 https://$server_name$request_uri;
    }

    server {
        listen 443 ssl;
        server_name pulse.yourdomain.com;

        ssl_certificate /etc/letsencrypt/live/pulse.yourdomain.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/pulse.yourdomain.com/privkey.pem;

        location / {
            proxy_pass http://api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        location /flower/ {
            proxy_pass http://flower:5555/;
            auth_basic "Restricted";
            auth_basic_user_file /etc/nginx/.htpasswd;
        }
    }
}
```

### 4. Create Environment File

Create `.env.prod`:

```bash
# Database
POSTGRES_USER=pulse_prod
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_DB=pulse_production

# Redis
REDIS_PASSWORD=your_redis_password_here

# Flower (Celery Monitor)
FLOWER_USER=admin
FLOWER_PASSWORD=secure_flower_password

# Application
DEBUG=false
```

### 5. Deploy

```bash
# SSH to your server
ssh user@your-server.com

# Clone repository
git clone https://github.com/yourusername/pulse_jobs.git
cd pulse_jobs

# Copy environment file
scp .env.prod user@your-server.com:~/pulse_jobs/.env

# Start services
docker-compose -f docker-compose.prod.yml up -d

# Scale workers
docker-compose -f docker-compose.prod.yml up -d --scale worker=3

# View logs
docker-compose -f docker-compose.prod.yml logs -f
```

---

## Option 2: AWS ECS (Managed Containers)

Best for: Medium scale, AWS-native, managed infrastructure.

### Architecture

```
Internet
    │
    ▼
┌───────────────────┐
│  Application LB   │
└─────────┬─────────┘
          │
          ▼
┌─────────────────────────────────────────────┐
│                 ECS Cluster                  │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐     │
│  │ API x3  │  │Worker x5│  │ Flower  │     │
│  └─────────┘  └─────────┘  └─────────┘     │
└─────────────────────────────────────────────┘
          │                   │
          ▼                   ▼
    ┌───────────┐      ┌───────────────┐
    │    RDS    │      │ ElastiCache   │
    │PostgreSQL │      │    (Redis)    │
    └───────────┘      └───────────────┘
```

### 1. Create ECR Repository

```bash
# Create container registry
aws ecr create-repository --repository-name pulse-api

# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin 123456789.dkr.ecr.us-east-1.amazonaws.com

# Build and push
docker build -t pulse-api -f api/Dockerfile.prod api/
docker tag pulse-api:latest 123456789.dkr.ecr.us-east-1.amazonaws.com/pulse-api:latest
docker push 123456789.dkr.ecr.us-east-1.amazonaws.com/pulse-api:latest
```

### 2. Create ECS Task Definition

```json
{
  "family": "pulse-api",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::123456789:role/ecsTaskExecutionRole",
  "containerDefinitions": [
    {
      "name": "api",
      "image": "123456789.dkr.ecr.us-east-1.amazonaws.com/pulse-api:latest",
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {"name": "DEBUG", "value": "false"}
      ],
      "secrets": [
        {
          "name": "DATABASE_URL",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789:secret:pulse/database"
        },
        {
          "name": "REDIS_URL",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789:secret:pulse/redis"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/pulse",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "api"
        }
      }
    }
  ]
}
```

### 3. Create Infrastructure with Terraform

```hcl
# main.tf
provider "aws" {
  region = "us-east-1"
}

# RDS PostgreSQL
resource "aws_db_instance" "pulse" {
  identifier        = "pulse-db"
  engine            = "postgres"
  engine_version    = "15"
  instance_class    = "db.t3.micro"
  allocated_storage = 20
  
  db_name  = "pulse"
  username = "pulse"
  password = var.db_password
  
  vpc_security_group_ids = [aws_security_group.db.id]
  db_subnet_group_name   = aws_db_subnet_group.pulse.name
  
  skip_final_snapshot = true
}

# ElastiCache Redis
resource "aws_elasticache_cluster" "pulse" {
  cluster_id           = "pulse-redis"
  engine               = "redis"
  node_type            = "cache.t3.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  
  security_group_ids = [aws_security_group.redis.id]
  subnet_group_name  = aws_elasticache_subnet_group.pulse.name
}

# ECS Cluster
resource "aws_ecs_cluster" "pulse" {
  name = "pulse-cluster"
}

# ECS Service (API)
resource "aws_ecs_service" "api" {
  name            = "pulse-api"
  cluster         = aws_ecs_cluster.pulse.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 3
  launch_type     = "FARGATE"
  
  network_configuration {
    subnets         = var.private_subnets
    security_groups = [aws_security_group.api.id]
  }
  
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
}
```

---

## Option 3: Kubernetes (Large Scale)

Best for: Large scale, multi-region, complex deployments.

### Kubernetes Manifests

#### API Deployment

```yaml
# k8s/api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pulse-api
  labels:
    app: pulse
    component: api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: pulse
      component: api
  template:
    metadata:
      labels:
        app: pulse
        component: api
    spec:
      containers:
        - name: api
          image: your-registry/pulse-api:latest
          ports:
            - containerPort: 8000
          env:
            - name: DEBUG
              value: "false"
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: pulse-secrets
                  key: database-url
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: pulse-secrets
                  key: redis-url
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 15
            periodSeconds: 20
```

#### Worker Deployment with HPA

```yaml
# k8s/worker-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pulse-worker
  labels:
    app: pulse
    component: worker
spec:
  replicas: 2
  selector:
    matchLabels:
      app: pulse
      component: worker
  template:
    metadata:
      labels:
        app: pulse
        component: worker
    spec:
      containers:
        - name: worker
          image: your-registry/pulse-api:latest
          command: ["celery", "-A", "app.celery_app", "worker", "--loglevel=info"]
          env:
            - name: CELERY_BROKER_URL
              valueFrom:
                secretKeyRef:
                  name: pulse-secrets
                  key: redis-url
          resources:
            requests:
              memory: "512Mi"
              cpu: "500m"
            limits:
              memory: "1Gi"
              cpu: "1"
---
# Horizontal Pod Autoscaler
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: pulse-worker-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: pulse-worker
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: External
      external:
        metric:
          name: redis_queue_length
          selector:
            matchLabels:
              queue: celery
        target:
          type: AverageValue
          averageValue: 10  # Scale up if queue length > 10 per pod
```

#### Service and Ingress

```yaml
# k8s/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: pulse-api
spec:
  selector:
    app: pulse
    component: api
  ports:
    - port: 80
      targetPort: 8000
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: pulse-ingress
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
    - hosts:
        - pulse.yourdomain.com
      secretName: pulse-tls
  rules:
    - host: pulse.yourdomain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: pulse-api
                port:
                  number: 80
```

---

## Production Best Practices

### 1. Security

```yaml
# Use non-root user
securityContext:
  runAsNonRoot: true
  runAsUser: 1000

# Read-only filesystem
securityContext:
  readOnlyRootFilesystem: true

# Network policies
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: pulse-api
spec:
  podSelector:
    matchLabels:
      app: pulse
      component: api
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: pulse
              component: ingress
```

### 2. Monitoring

Add Prometheus metrics:

```python
# api/app/core/metrics.py
from prometheus_client import Counter, Histogram

JOBS_CREATED = Counter('pulse_jobs_created_total', 'Total jobs created', ['task_name'])
JOBS_COMPLETED = Counter('pulse_jobs_completed_total', 'Total jobs completed', ['task_name', 'status'])
JOB_DURATION = Histogram('pulse_job_duration_seconds', 'Job processing duration', ['task_name'])
```

### 3. Logging

Use structured logging:

```python
import structlog

logger = structlog.get_logger()

logger.info(
    "job_created",
    job_id=job.id,
    task_name=job.task_name,
    priority=job.priority
)
```

### 4. Health Checks

```python
@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    checks = {}
    
    # Database check
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"unhealthy: {e}"
    
    # Redis check
    try:
        redis_client.ping()
        checks["redis"] = "healthy"
    except Exception as e:
        checks["redis"] = f"unhealthy: {e}"
    
    status = "healthy" if all("unhealthy" not in v for v in checks.values()) else "degraded"
    status_code = 200 if status == "healthy" else 503
    
    return JSONResponse({"status": status, "checks": checks}, status_code=status_code)
```

---

## Database Migrations

### Using Alembic

```bash
# Initialize Alembic
cd api
alembic init alembic

# Configure alembic.ini
sqlalchemy.url = postgresql+asyncpg://...

# Create migration
alembic revision --autogenerate -m "Add jobs table"

# Run migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

### Migration in CI/CD

```yaml
# Run migrations before deploying new code
- name: Run migrations
  run: |
    docker run --rm \
      -e DATABASE_URL=${{ secrets.DATABASE_URL }} \
      your-registry/pulse-api:${{ github.sha }} \
      alembic upgrade head
```
