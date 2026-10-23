"""
THE BACKGROUND WORKER

Takes jobs from the Redis queue one by one, runs the pipeline for each,
saves the finished cases in Postgres and logs one line per case.
It also runs the notifier: new alerts are sent straight after each job,
and unconfirmed ones are checked for escalation about once a minute.

    Redis queue -> worker -> pipeline -> Postgres -> notifier

A job that fails is logged and kept in the failed list; the worker carries on.
Log lines identify cases by reference only: never names, report text or quotes.

Run from the project folder (Postgres, Redis and Ollama must be running):
    python worker.py
Stop with Ctrl + C.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.db import create_tables
from app.llm.client import check_ollama
from app.services import notifier, queue
from app.services.case_store import save_case
from app.services.pipeline import process_field_submission, process_helpline_call, process_upload

# 1. LOGGING
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger("worker")
# Presidio logs every recognizer it loads (about 45 lines), and Whisper and its
# download library log every request; keep only their errors.
for noisy in ("presidio-analyzer", "presidio-anonymizer", "faster_whisper", "httpx"):
    logging.getLogger(noisy).setLevel(logging.ERROR)


# 2. RUN ONE JOB
def run_job(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the pipeline function for this kind of job. Returns the finished cases."""
    kind, data, original_key = job["kind"], job["data"], job.get("original_key")
    if kind == "field":
        return [process_field_submission(data, original_key=original_key)]
    if kind == "helpline":
        return [process_helpline_call(data, original_key=original_key)]
    if kind == "upload":
        return process_upload(data, original_key=original_key)
    raise ValueError(f"Unknown job kind: {kind!r}")


def describe(case: dict[str, Any], case_ref: str) -> str:
    """One log line: reference, outcome and alert reasons. No personal information."""
    outcome = case.get("band") or case["status"]
    alert = f", alert ({', '.join(case['urgent_reasons'])})" if case.get("alert") else ""
    return f"{case['channel']:8} {case_ref:24} saved: {outcome}{alert}"


def handle(job: dict[str, Any]) -> None:
    """Run, save and log one job; on any error, keep the job in the failed list."""
    try:
        for case in run_job(job):
            case_ref = save_case(case)
            log.info(describe(case, case_ref))
    except Exception as error:      # one bad job must never stop the worker
        log.error("job %s (%s) failed: %s", job["id"][:8], job["kind"], type(error).__name__)
        queue.record_failure(job, f"{type(error).__name__}: {error}")


# 3. ALERTS
ALERT_CHECK_SECONDS = 60


def check_alerts() -> None:
    """Send new alerts and escalate overdue ones; a notifier error never stops the worker."""
    try:
        notifier.run_once()
    except Exception as error:
        log.error("notifier failed: %s", type(error).__name__)


# 4. MAIN LOOP
def main() -> None:
    create_tables()
    if not check_ollama():
        log.warning("Ollama is not reachable: cases will be saved as 'could not assess'")
    log.info("worker started; waiting for jobs (%s)", queue.queue_sizes())
    last_check = 0.0
    try:
        while True:
            job = queue.next_job(timeout=5)
            if job:
                handle(job)
            if job or time.monotonic() - last_check >= ALERT_CHECK_SECONDS:
                check_alerts()
                last_check = time.monotonic()
    except KeyboardInterrupt:
        log.info("worker stopped (%s)", queue.queue_sizes())


if __name__ == "__main__":
    main()
