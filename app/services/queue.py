"""The job queue (Redis): the waiting line between the API and the worker.

The API adds a job and answers straight away; the worker takes jobs one by one,
oldest first. A job that fails is moved to a separate "failed" list with its
error, so it is never silently lost and can be retried.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import redis

from config import REDIS_URL

# 1. CONFIGURATION
QUEUE = "aicare:jobs"
FAILED = "aicare:jobs:failed"
KINDS = {"field", "helpline", "upload"}   # which pipeline function the worker runs


def client() -> redis.Redis:
    # redis-py 8 stops reading after 5 seconds by default, the same time the worker
    # waits for a job; allow longer so an empty queue is not mistaken for an error.
    return redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=30)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# 2. ADD A JOB
def enqueue(kind: str, data: dict[str, Any], original_key: str | None = None,
            connection: redis.Redis | None = None) -> str:
    """Add a job to the end of the line and return its job ID."""
    if kind not in KINDS:
        raise ValueError(f"Unknown job kind: {kind!r}")
    job = {"id": str(uuid.uuid4()), "kind": kind, "data": data,
           "original_key": original_key, "queued_at": now()}
    (connection or client()).lpush(QUEUE, json.dumps(job))
    return job["id"]


# 3. TAKE THE NEXT JOB
def next_job(timeout: int = 5, connection: redis.Redis | None = None) -> dict[str, Any] | None:
    """The oldest waiting job, or None if none arrives within `timeout` seconds."""
    item = (connection or client()).brpop([QUEUE], timeout=timeout)
    return json.loads(item[1]) if item else None


# 4. FAILED JOBS
def record_failure(job: dict[str, Any], error: str, connection: redis.Redis | None = None) -> None:
    """Keep a failed job with its error, so a person can see it and retry it."""
    (connection or client()).lpush(FAILED, json.dumps({**job, "error": error, "failed_at": now()}))


def retry_failed(connection: redis.Redis | None = None) -> int:
    """Put every failed job back in the queue (after the cause is fixed). Returns how many."""
    connection = connection or client()
    moved = 0
    while (item := connection.rpop(FAILED)) is not None:
        job = json.loads(item)
        job.pop("error", None), job.pop("failed_at", None)
        connection.lpush(QUEUE, json.dumps(job))
        moved += 1
    return moved


def queue_sizes(connection: redis.Redis | None = None) -> dict[str, int]:
    connection = connection or client()
    return {"waiting": connection.llen(QUEUE), "failed": connection.llen(FAILED)}
