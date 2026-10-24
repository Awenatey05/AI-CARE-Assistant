"""The worker's logic: the right pipeline per job, one log line per case, failures kept (no Redis, no Postgres)."""

from __future__ import annotations

import logging

import pytest

import worker


@pytest.fixture
def saved(monkeypatch):
    """Replace saving and the failed list; record what happened."""
    record = {"saved": [], "failed": []}
    monkeypatch.setattr(worker, "save_case", lambda case: record["saved"].append(case) or "NR-TML-GUM-0001-2026")
    monkeypatch.setattr(worker.queue, "record_failure", lambda job, error: record["failed"].append(error))
    monkeypatch.setattr(worker, "save_case_chunks", lambda case_id, ref, region, text: 2 if text else 0)
    return record


def a_case(**changes):
    case = {"id": "c1", "channel": "field", "status": "assessed", "band": "High", "alert": True,
            "urgent_reasons": ["critical_indicator:1"], "child_name": "Ama Mensah", "masked_text": "secret text"}
    return {**case, **changes}


def test_each_kind_runs_its_pipeline(monkeypatch, saved):
    monkeypatch.setattr(worker, "process_field_submission", lambda data, original_key=None: a_case(id="f"))
    monkeypatch.setattr(worker, "process_helpline_call", lambda data, original_key=None: a_case(id="h"))
    monkeypatch.setattr(worker, "process_upload", lambda data, original_key=None: [a_case(id="u1"), a_case(id="u2")])
    for kind in ("field", "helpline", "upload"):
        worker.handle({"id": "job-1", "kind": kind, "data": {}})
    assert [c["id"] for c in saved["saved"]] == ["f", "h", "u1", "u2"]


def test_log_line_has_no_personal_information(monkeypatch, saved, caplog):
    monkeypatch.setattr(worker, "process_field_submission", lambda data, original_key=None: a_case())
    with caplog.at_level(logging.INFO, logger="worker"):
        worker.handle({"id": "job-1", "kind": "field", "data": {}})
    line = caplog.records[-1].getMessage()
    assert "NR-TML-GUM-0001-2026" in line and "High" in line and "critical_indicator:1" in line
    assert "Ama" not in line and "secret text" not in line


def test_failed_job_is_kept_and_the_worker_carries_on(monkeypatch, saved, caplog):
    def broken(data, original_key=None):
        raise RuntimeError("database is down")
    monkeypatch.setattr(worker, "process_field_submission", broken)
    with caplog.at_level(logging.ERROR, logger="worker"):
        worker.handle({"id": "job-12345678", "kind": "field", "data": {}})     # does not raise
    assert saved["failed"] == ["RuntimeError: database is down"]
    assert "job-1234 (field) failed" in caplog.records[-1].getMessage()


def test_status_shown_when_there_is_no_band():
    line = worker.describe(a_case(band=None, status="not_scored_no_consent", alert=False), "OT-JSK-0002-2026")
    assert line.endswith("saved: not_scored_no_consent")


def test_notifier_error_does_not_stop_the_worker(monkeypatch, caplog):
    def broken():
        raise ConnectionError("Postgres is down")
    monkeypatch.setattr(worker.notifier, "run_once", broken)
    with caplog.at_level(logging.ERROR, logger="worker"):
        worker.check_alerts()                                            # does not raise
    assert caplog.records[-1].getMessage() == "notifier failed: ConnectionError"


def test_log_line_counts_chunks(monkeypatch, saved, caplog):
    monkeypatch.setattr(worker, "process_field_submission", lambda data, original_key=None: a_case())
    with caplog.at_level(logging.INFO, logger="worker"):
        worker.handle({"id": "job-1", "kind": "field", "data": {}})
    assert caplog.records[-1].getMessage().endswith(", 2 chunks")


def test_embedding_failure_keeps_the_case_and_the_job(monkeypatch, saved, caplog):
    def ollama_down(case_id, ref, region, text):
        raise ConnectionError("Ollama is not running")
    monkeypatch.setattr(worker, "process_field_submission", lambda data, original_key=None: a_case())
    monkeypatch.setattr(worker, "save_case_chunks", ollama_down)
    with caplog.at_level(logging.INFO, logger="worker"):
        worker.handle({"id": "job-1", "kind": "field", "data": {}})
    messages = [r.getMessage() for r in caplog.records if r.name == "worker"]
    assert len(saved["saved"]) == 1 and saved["failed"] == []
    assert "NR-TML-GUM-0001-2026 not yet searchable: ConnectionError" in messages
    assert "secret text" not in " ".join(messages)
