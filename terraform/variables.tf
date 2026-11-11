# ============================================
# Input Variables
# ============================================

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "ap-south-1" # Mumbai
}

variable "environment" {
  description = "Environment name (dev, staging, production)"
  type        = string
  default     = "production"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "pulse"
}

# ---- Networking ----

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = ["ap-south-1a", "ap-south-1b"]
}

# ---- Database ----

variable "db_instance_class" {
  description = "RDS instance type"
  type        = string
  default     = "db.t3.micro"
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "pulse_jobs"
}

variable "db_username" {
  description = "Database master username"
  type        = string
  default     = "pulse"
  sensitive   = true
}

variable "db_password" {
  description = "Database master password"
  type        = string
  sensitive   = true
}

# ---- Redis ----

variable "redis_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.t3.micro"
}

# ---- ECS ----

variable "api_cpu" {
  description = "CPU units for API task (1024 = 1 vCPU)"
  type        = number
  default     = 256
}

variable "api_memory" {
  description = "Memory (MB) for API task"
  type        = number
  default     = 512
}

variable "api_desired_count" {
  description = "Number of API task instances"
  type        = number
  default     = 2
}

variable "worker_cpu" {
  description = "CPU units for Worker task"
  type        = number
  default     = 512
}

variable "worker_memory" {
  description = "Memory (MB) for Worker task"
  type        = number
  default     = 1024
}

variable "worker_min_count" {
  description = "Minimum number of worker tasks"
  type        = number
  default     = 2
}

variable "worker_max_count" {
  description = "Maximum number of worker tasks (auto-scaling)"
  type        = number
  default     = 10
}
