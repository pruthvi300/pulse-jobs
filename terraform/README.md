# Terraform Infrastructure as Code - Pulse Jobs

## Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │              AWS Cloud (ap-south-1)          │
                    │                                              │
  Internet ───────▶ │  ┌──────────┐     ┌────────────────────┐    │
                    │  │   ALB    │────▶│  ECS Fargate        │    │
                    │  │ (public) │     │  ┌─────┐ ┌───────┐ │    │
                    │  └──────────┘     │  │ API │ │Workers│ │    │
                    │                    │  │ x2  │ │ 2-10 │ │    │
                    │                    │  └──┬──┘ └───┬───┘ │    │
                    │                    └─────┼────────┼─────┘    │
                    │                          │        │          │
                    │                    ┌─────▼────────▼─────┐    │
                    │   Private Subnet   │  ┌─────┐ ┌──────┐ │    │
                    │                    │  │Redis│ │ RDS  │ │    │
                    │                    │  │     │ │Postgr│ │    │
                    │                    │  └─────┘ └──────┘ │    │
                    │                    └────────────────────┘    │
                    └─────────────────────────────────────────────┘
```

## What Gets Provisioned

| Resource | AWS Service | Purpose |
|----------|-------------|---------|
| VPC | VPC | Isolated network with public/private subnets |
| Load Balancer | ALB | Routes traffic to API containers |
| API Server | ECS Fargate | 2 FastAPI containers (auto-healing) |
| Workers | ECS Fargate | 2-10 Celery containers (auto-scaling) |
| Database | RDS PostgreSQL 15 | Managed DB with backups + encryption |
| Message Broker | ElastiCache Redis 7 | Celery broker + result backend |
| Docker Registry | ECR | Private Docker image storage |
| Logs | CloudWatch | Centralized logging (30-day retention) |

## Usage

### Prerequisites
- AWS CLI configured (`aws configure`)
- Terraform >= 1.5 installed

### Deploy

```bash
cd terraform

# Initialize (downloads AWS provider)
terraform init

# Preview what will be created
terraform plan -var="db_password=YourStrongPassword123!"

# Apply (creates everything)
terraform apply -var="db_password=YourStrongPassword123!"

# Outputs
terraform output alb_dns_name    # → Your API endpoint
terraform output ecr_repository_url  # → Push Docker images here
```

### Push Docker Image

```bash
# Login to ECR
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin $(terraform output -raw ecr_repository_url)

# Build and push
docker build -t pulse-api ./api
docker tag pulse-api:latest $(terraform output -raw ecr_repository_url):latest
docker push $(terraform output -raw ecr_repository_url):latest

# Force new deployment
aws ecs update-service --cluster pulse-cluster --service pulse-api --force-new-deployment
aws ecs update-service --cluster pulse-cluster --service pulse-worker --force-new-deployment
```

### Tear Down

```bash
terraform destroy -var="db_password=YourStrongPassword123!"
```

## Cost Estimate (ap-south-1 Mumbai)

| Resource | Monthly Cost |
|----------|-------------|
| ECS Fargate (API x2) | ~$15 |
| ECS Fargate (Workers x2-10) | ~$15-75 |
| RDS db.t3.micro | ~$15 |
| ElastiCache cache.t3.micro | ~$12 |
| ALB | ~$20 |
| NAT Gateway | ~$35 |
| **Total** | **~$112-172/month** |

## Key Design Decisions

### Why ECS Fargate over EKS?
- **EKS control plane** costs $72/month just to exist — before any pods run
- **Fargate** is serverless — no nodes to manage, pay per task
- For this scale (2-10 workers), EKS is overkill
- We still have K8s manifests in `k8s/` for environments with existing K8s clusters

### Why Application Auto Scaling matches K8s HPA?
Both use the same concept — scale workers based on CPU utilization:
- **K8s HPA**: `averageUtilization: 70` → scale 2-10 pods
- **ECS Auto Scaling**: `target_value: 70.0` → scale 2-10 tasks
- Same cooldown periods (60s up, 300s down)

### Security
- **Private subnets**: RDS, Redis, and ECS tasks are NOT internet-accessible
- **Security groups**: Defense-in-depth — ALB → ECS → RDS/Redis chain
- **Encryption**: RDS encrypted at rest, ECR scans images on push
- **No hardcoded secrets**: Passwords passed via variables, never in code
