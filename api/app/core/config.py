"""
Application settings, loaded from environment variables (and `.env`).

Same image, same settings class for the API and the Celery workers;
only the start command differs.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    PROJECT_NAME: str = "Pulse - Job Processing Platform"
    VERSION: str = "1.1.0"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # Async URL for the API. Workers derive a sync (psycopg) URL from it.
    DATABASE_URL: str = "postgresql+asyncpg://pulse:pulse_secret@localhost:5432/pulse_jobs"

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # Retry policy: delay = min(BASE * 2**retries, MAX), then full jitter.
    DEFAULT_MAX_RETRIES: int = 3
    RETRY_BACKOFF_BASE_SECONDS: float = 30.0
    RETRY_BACKOFF_MAX_SECONDS: float = 600.0

    # How long the API waits for the broker before giving up on a submission.
    BROKER_PUBLISH_TIMEOUT_SECONDS: float = 5.0

    # Redis redelivers a task that a dead worker never acknowledged after this many
    # seconds. Keep it above the longest retry countdown + task runtime.
    CELERY_VISIBILITY_TIMEOUT_SECONDS: int = 3600

    # Knobs for the simulated tasks (load tests set these).
    SIMULATED_LATENCY_SCALE: float = 1.0
    SIMULATED_EMAIL_FAILURE_RATE: float = 0.3
    SIMULATED_WEBHOOK_FAILURE_RATE: float = 0.2

    @property
    def SYNC_DATABASE_URL(self) -> str:
        url = self.DATABASE_URL
        for async_driver, sync_driver in (("+asyncpg", "+psycopg"), ("+aiosqlite", "")):
            url = url.replace(async_driver, sync_driver)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
