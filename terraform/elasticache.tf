# ============================================
# ElastiCache Redis (Message Broker + Cache)
# ============================================

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${var.project_name}-redis-subnet-group"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${var.project_name}-redis"
  engine               = "redis"
  engine_version       = "7.0"
  node_type            = var.redis_node_type
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.redis.name
  security_group_ids = [aws_security_group.redis.id]

  # Maintenance
  maintenance_window = "Mon:05:00-Mon:06:00"

  # Snapshots
  snapshot_retention_limit = 3
  snapshot_window          = "02:00-03:00"

  tags = {
    Name = "${var.project_name}-redis"
  }
}
