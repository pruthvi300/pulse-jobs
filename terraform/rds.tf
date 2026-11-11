# ============================================
# RDS PostgreSQL
# ============================================
# Why RDS over self-managed PostgreSQL?
#   - Automated backups (7-day retention)
#   - Automated patching
#   - Multi-AZ failover (optional)
#   - CloudWatch monitoring built-in
# ============================================

resource "aws_db_subnet_group" "postgres" {
  name       = "${var.project_name}-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${var.project_name}-db-subnet-group"
  }
}

resource "aws_db_instance" "postgres" {
  identifier     = "${var.project_name}-db"
  engine         = "postgres"
  engine_version = "15"
  instance_class = var.db_instance_class

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  allocated_storage     = 20
  max_allocated_storage = 100  # Auto-scaling storage

  db_subnet_group_name   = aws_db_subnet_group.postgres.name
  vpc_security_group_ids = [aws_security_group.database.id]

  # Backups
  backup_retention_period = 7
  backup_window           = "03:00-04:00" # 3-4 AM IST

  # Maintenance
  maintenance_window = "Mon:04:00-Mon:05:00"

  # Security
  publicly_accessible = false     # Private subnet only
  storage_encrypted   = true      # Encrypt at rest
  skip_final_snapshot = true      # For dev — set false in production

  # Performance
  performance_insights_enabled = true

  tags = {
    Name = "${var.project_name}-db"
  }
}
