"""The Redis job queue, on the real Redis but with separate test queue names (removed afterwards)."""

from __future__ import annotations

import pytest
import redis

from app.services import queue


@pytest.fixture
def r(monkeypatch):
    connection = queue.client()
    try:
        connection.ping()
    except redis.exceptions.ConnectionError:
        pytest.skip("Redis is not running (docker compose up -d)")
    monkeypatch.setattr(queue, "QUEUE", "aicare:test:jobs")
    monkeypatch.setattr(queue, "FAILED", "aicare:test:failed")
    connection.delete("aicare:test:jobs", "aicare:test:failed")
    yield connection
    connection.delete("aicare:test:jobs", "aicare:test:failed")


def test_jobs_come_out_oldest_first(r):
    first = queue.enqueue("field", {"case_uuid": "a"}, connection=r)
    second = queue.enqueue("helpline", {"report_id": "b"}, connection=r)
    assert queue.next_job(timeout=1, connection=r)["id"] == first
    assert queue.next_job(timeout=1, connection=r)["id"] == second
    assert queue.next_job(timeout=1, connection=r) is None


def test_job_keeps_its_data(r):
    queue.enqueue("upload", {"upload_id": "UP-1"}, original_key="uploads/UP-1.pdf", connection=r)
    job = queue.next_job(timeout=1, connection=r)
    assert (job["kind"], job["data"], job["original_key"]) == ("upload", {"upload_id": "UP-1"}, "uploads/UP-1.pdf")


def test_unknown_kind_rejected(r):
    with pytest.raises(ValueError):
        queue.enqueue("email", {}, connection=r)


def test_failed_job_is_kept_and_can_be_retried(r):
    queue.enqueue("field", {"case_uuid": "a"}, connection=r)
    job = queue.next_job(timeout=1, connection=r)
    queue.record_failure(job, "Ollama is not running", connection=r)
    assert queue.queue_sizes(connection=r) == {"waiting": 0, "failed": 1}
    assert queue.retry_failed(connection=r) == 1
    again = queue.next_job(timeout=1, connection=r)
    assert again["id"] == job["id"] and "error" not in again


def test_waiting_on_an_empty_queue_is_not_an_error(r):
    # The worker waits 5 seconds for a job; redis-py 8 used to give up reading at exactly 5.
    assert queue.next_job(timeout=5, connection=r) is None
