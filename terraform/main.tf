# ============================================
# Pulse Jobs - Terraform AWS Infrastructure
# ============================================
# This provisions the cloud infrastructure for
# running Pulse on AWS with:
#   - VPC with public/private subnets
#   - ECS Fargate for containerized services
#   - RDS PostgreSQL for persistence
#   - ElastiCache Redis for message broker
#   - ALB for load balancing
#   - ECR for Docker image registry
# ============================================
#
# ⚠️  SAFETY: Provider block is commented out.
#     This means `terraform init` and `terraform apply`
#     CANNOT run. Nothing will be created on AWS.
#     To actually deploy, uncomment the blocks below
#     and configure AWS credentials first.
# ============================================

# terraform {
#   required_version = ">= 1.5"
#
#   required_providers {
#     aws = {
#       source  = "hashicorp/aws"
#       version = "~> 5.0"
#     }
#   }
#
#   # Remote state storage (uncomment for production)
#   # backend "s3" {
#   #   bucket         = "pulse-terraform-state"
#   #   key            = "infrastructure/terraform.tfstate"
#   #   region         = "ap-south-1"
#   #   dynamodb_table = "pulse-terraform-locks"
#   #   encrypt        = true
#   # }
# }
#
# provider "aws" {
#   region = var.aws_region
#
#   default_tags {
#     tags = {
#       Project     = "pulse-jobs"
#       Environment = var.environment
#       ManagedBy   = "terraform"
#     }
#   }
# }
