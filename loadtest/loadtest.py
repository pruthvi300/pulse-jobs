"""
Pulse load test: submit jobs at a fixed concurrency, wait for workers to drain
them, then check every job reached a terminal state.

Run against an empty database (counts come from /jobs/stats/summary):

    python loadtest/loadtest.py --jobs 5000 --concurrency 50 --duplicate-rate 0.1

Measures:
- submission throughput and latency percentiles (POST /jobs)
- idempotency: duplicate submissions must return the original job (200), never a new one
- drain throughput: jobs reaching a terminal state per second
- correctness: no job lost or stuck; dead-letter count vs. the expected
  failure_rate ** (max_retries + 1)

Uses aiohttp: httpx's async client tops out around 200 req/s at this
concurrency and would measure itself instead of the server.
"""

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from collections import Counter

import aiohttp

TERMINAL = ("completed", "failed", "dead_letter")
ACTIVE = ("pending", "running", "retrying")


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p))]


async def submit_all(client: aiohttp.ClientSession, args) -> dict:
    run = uuid.uuid4().hex[:8]
    keys = [f"lt-{run}-{i}" for i in range(args.jobs)]
    # Some submissions reuse an earlier key, as a client retrying after a timeout would.
    requests = keys + random.sample(keys, int(args.jobs * args.duplicate_rate))
    random.shuffle(requests)

    queue: asyncio.Queue[str] = asyncio.Queue()
    for key in requests:
        queue.put_nowait(key)
    latencies: list[float] = []
    codes: Counter[int] = Counter()
    ids_by_key: dict[str, set[int]] = {}

    async def worker():
        while not queue.empty():
            key = queue.get_nowait()
            body = {
                "task_name": "send_email",
                "payload": {"to": "load@example.com", "subject": "load test", "body": key},
                "priority": random.choice(["critical", "high", "default", "low"]),
                "idempotency_key": key,
                "max_retries": args.max_retries,
            }
            start = time.perf_counter()
            try:
                async with client.post("/api/v1/jobs/", json=body) as resp:
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                codes[type(exc).__name__] += 1
                continue
            latencies.append(time.perf_counter() - start)
            codes[resp.status] += 1
            if resp.status in (200, 201):
                ids_by_key.setdefault(key, set()).add(data["id"])

    start = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(args.concurrency)))
    elapsed = time.perf_counter() - start

    return {
        "requests": len(requests),
        "unique_keys": len(keys),
        "elapsed_s": round(elapsed, 2),
        "requests_per_s": round(len(requests) / elapsed, 1),
        "latency_ms": {
            "p50": round(percentile(latencies, 0.50) * 1000, 1),
            "p95": round(percentile(latencies, 0.95) * 1000, 1),
            "p99": round(percentile(latencies, 0.99) * 1000, 1),
            "max": round(max(latencies) * 1000, 1),
            "mean": round(statistics.mean(latencies) * 1000, 1),
        },
        "status_codes": {str(k): v for k, v in sorted(codes.items(), key=str)},
        # A key mapped to more than one job id means idempotency failed.
        "keys_with_duplicate_jobs": sum(1 for ids in ids_by_key.values() if len(ids) > 1),
        "job_ids": sorted({i for ids in ids_by_key.values() for i in ids}),
    }


async def get_json(client: aiohttp.ClientSession, path: str) -> dict:
    async with client.get(path) as resp:
        resp.raise_for_status()
        return await resp.json()


async def wait_for_drain(client: aiohttp.ClientSession, timeout: float, started: float) -> dict:
    samples = []
    while True:
        stats = await get_json(client, "/api/v1/jobs/stats/summary")
        samples.append((round(time.perf_counter() - started, 1), sum(stats[s] for s in TERMINAL)))
        if sum(stats[s] for s in ACTIVE) == 0:
            return {"drained": True, "stats": stats, "samples": samples}
        if time.perf_counter() - started > timeout:
            return {"drained": False, "stats": stats, "samples": samples}
        await asyncio.sleep(1)


async def verify(client: aiohttp.ClientSession, job_ids: list[int], concurrency: int) -> dict:
    statuses: Counter[str] = Counter()
    attempts: Counter[int] = Counter()
    sem = asyncio.Semaphore(concurrency)

    async def check(job_id: int):
        async with sem:
            job = await get_json(client, f"/api/v1/jobs/{job_id}")
        statuses[job["status"]] += 1
        attempts[job["attempts"]] += 1

    await asyncio.gather(*(check(i) for i in job_ids))
    return {"statuses": dict(statuses), "attempts_histogram": dict(sorted(attempts.items()))}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--jobs", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--duplicate-rate", type=float, default=0.1)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--failure-rate", type=float, default=None, help="Worker's injected failure rate, for the report")
    parser.add_argument("--drain-timeout", type=float, default=600)
    parser.add_argument("--out", help="Write the JSON report here")
    args = parser.parse_args()

    connector = aiohttp.TCPConnector(limit=args.concurrency)
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(args.base_url, connector=connector, timeout=timeout) as client:
        started = time.perf_counter()
        submit = await submit_all(client, args)
        drain = await wait_for_drain(client, args.drain_timeout, started)
        drain_elapsed = drain["samples"][-1][0]
        check = await verify(client, submit["job_ids"], args.concurrency)

    total = len(submit["job_ids"])
    terminal = sum(check["statuses"].get(s, 0) for s in TERMINAL)
    report = {
        "config": {k: v for k, v in vars(args).items() if k != "out"},
        "submit": {k: v for k, v in submit.items() if k != "job_ids"},
        "drain": {
            "drained": drain["drained"],
            "seconds_from_first_submit": drain_elapsed,
            "jobs_per_s": round(total / drain_elapsed, 1) if drain_elapsed else None,
        },
        "verify": {
            **check,
            "jobs_created": total,
            "lost_or_stuck": total - terminal,
            "extra_jobs_created": total - submit["unique_keys"],
        },
    }
    if args.failure_rate is not None:
        report["verify"]["expected_dead_letter"] = round(total * args.failure_rate ** (args.max_retries + 1), 1)

    print(json.dumps(report, indent=2))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
