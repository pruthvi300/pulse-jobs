# Load test

`loadtest.py` submits jobs at a fixed concurrency, waits for the workers to drain
them, then fetches every job and checks it reached a terminal state.

It checks four things:

- **Submission:** throughput and latency percentiles for `POST /api/v1/jobs/`.
- **Idempotency:** a share of submissions reuse an earlier key, as a client retrying
  after a timeout would. Each one must return the original job (200), never a new one.
- **Drain:** how fast jobs reach `completed` / `failed` / `dead_letter`.
- **Correctness:** no job lost or stuck, and the dead-letter count close to
  `failure_rate ** (max_retries + 1)`.

## How to run it

```bash
pip install -r loadtest/requirements.txt

# Start the stack with the simulations sped up so a run takes about a minute.
# The retry logic is unchanged; only the delays are shorter.
SIMULATED_LATENCY_SCALE=0.01 RETRY_BACKOFF_BASE_SECONDS=0.5 RETRY_BACKOFF_MAX_SECONDS=4 \
  docker-compose up -d

python loadtest/loadtest.py --jobs 5000 --concurrency 50 --duplicate-rate 0.1 \
  --failure-rate 0.3 --out loadtest/results/my_run.json
```

Use an empty database, or at least one with no active jobs: the script waits until
`/jobs/stats/summary` shows no pending, running or retrying jobs.

Celery 5.7 (kombu 5.7) needs Redis 6.2 or newer. The Compose file uses Redis 7. With an
older local Redis, the worker fails at startup with
`ResponseError: value is not an integer or out of range`.

## Results (2026-11-07)

Setup: one laptop (8 cores, 23 GB RAM). One uvicorn process, one Celery worker with
`--concurrency=8` (prefork), PostgreSQL 14 and Redis 6.0 running locally, Celery 5.5.
Each `send_email` task fails with a `TransientError` 30% of the time and sleeps 20 ms
when it succeeds. Raw report: [`results/2026-11-07_5000_jobs.json`](results/2026-11-07_5000_jobs.json).

5,000 unique jobs plus 500 duplicate submissions (5,500 requests), 50 concurrent clients,
`max_retries=3`:

| | Result |
|---|---|
| Submission throughput | 129 requests/s |
| Submission latency | p50 275 ms · p95 1,058 ms · p99 1,645 ms |
| Duplicate submissions | 500 of 500 returned the original job, 0 duplicate jobs created |
| Drain | all 5,000 jobs terminal 44.6 s after the first submission (~112 jobs/s) |
| Lost or stuck jobs | 0 |
| Outcome | 4,962 completed, 38 dead-lettered (expected ≈ 40.5 = 5,000 × 0.3⁴) |
| Attempts | 3,531 needed 1 attempt, 1,056 needed 2, 271 needed 3, 142 needed 4 |

### What limits throughput

The API is the bottleneck here, not the workers: the queue drained almost as fast as
jobs arrived. Submission runs in a single Python process, each request does a
PostgreSQL insert plus a Redis publish (in a thread, so the event loop isn't blocked),
and the database pool allows 15 connections for 50 clients. The latency percentiles are
mostly time spent waiting for a free connection.

To go faster, run more API processes (`uvicorn --workers N` or more replicas) and size
the pool to match.
