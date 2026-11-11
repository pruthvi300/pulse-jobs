# Pulse - common commands. Run `make help` for the list.

.PHONY: help dev dev-build stop logs logs-api logs-worker shell install test test-cov lint format clean scale-workers queue-length health

help:
	@echo "Development"
	@echo "  make dev             Start all services"
	@echo "  make dev-build       Rebuild and start all services"
	@echo "  make stop            Stop all services"
	@echo "  make logs            Follow logs (logs-api, logs-worker for one service)"
	@echo "  make shell           Shell in the API container"
	@echo "Testing"
	@echo "  make install         Install backend dev dependencies"
	@echo "  make test            Run tests (no Docker needed)"
	@echo "  make test-cov        Run tests with coverage"
	@echo "  make lint / format   Ruff check / format"
	@echo "Operations"
	@echo "  make scale-workers N=4   Run N worker containers"
	@echo "  make queue-length        Messages waiting in each queue"
	@echo "  make health              Call the readiness endpoint"
	@echo "  make clean               Stop services and delete this project's volumes"

dev:
	docker compose up

dev-build:
	docker compose up --build

stop:
	docker compose down

logs:
	docker compose logs -f

logs-api:
	docker compose logs -f api

logs-worker:
	docker compose logs -f worker

shell:
	docker compose exec api bash

install:
	cd api && pip install -r requirements-dev.txt

test:
	cd api && pytest -v

test-cov:
	cd api && pytest --cov=app --cov-report=term-missing --cov-report=html

lint:
	cd api && ruff check app tests

format:
	cd api && ruff format app tests && ruff check --fix app tests

clean:
	docker compose down -v --remove-orphans

scale-workers:
	docker compose up -d --scale worker=$(N)

queue-length:
	@for q in critical high default low; do printf "%-9s " $$q; docker compose exec -T redis redis-cli LLEN $$q; done

health:
	curl -s http://localhost:8000/health | python3 -m json.tool
