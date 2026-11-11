"""Pulse API entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.jobs import router as jobs_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.models.job import Base

logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Creates missing tables. For schema changes, add Alembic migrations.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Distributed job processing with retries, backoff and a dead-letter state",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(jobs_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["Root"])
async def root():
    return {"service": "Pulse Job Processing Platform", "version": settings.VERSION, "docs": "/docs"}


@app.get("/health/live", tags=["Root"])
async def liveness():
    """Process is up. Use for liveness probes (never depends on other services)."""
    return {"status": "ok"}


def _ping_redis() -> None:
    client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2, socket_timeout=2)
    try:
        client.ping()
    finally:
        client.close()


@app.get("/health", tags=["Root"])
async def readiness():
    """Checks PostgreSQL and the Redis broker. Use for readiness probes and load balancers."""
    checks = {}
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
    try:
        await asyncio.to_thread(_ping_redis)
        checks["broker"] = "ok"
    except Exception as exc:
        checks["broker"] = f"error: {type(exc).__name__}"

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "healthy" if healthy else "unhealthy", "checks": checks}, status_code=200 if healthy else 503
    )
