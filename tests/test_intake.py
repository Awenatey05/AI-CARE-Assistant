"""Intake: the original is saved before the job is queued (storage and queue replaced by fakes)."""

from __future__ import annotations

import pytest

from app.services import intake


@pytest.fixture
def steps(monkeypatch):
    """Record every save and every queued job, in order."""
    done = []
    monkeypatch.setattr(intake.storage, "save_json", lambda key, record: done.append(("save", key)) or key)
    monkeypatch.setattr(intake.storage, "save_file", lambda key, path: done.append(("save", key)) or key)
    monkeypatch.setattr(intake.queue, "enqueue",
                        lambda kind, data, original_key=None: done.append(("queue", kind, original_key, data)) or "job-1")
    return done


def test_kobo_form_saved_then_queued(steps):
    intake.receive_field_submission({"case_uuid": "abc"})
    assert steps[0] == ("save", "field/abc.json")
    assert steps[1][:3] == ("queue", "field", "field/abc.json")


def test_call_and_recording_saved_then_queued(steps):
    intake.receive_helpline_call({"report_id": "HL-1", "recording_file": "HL-1.m4a"}, "data/recordings/HL-1.m4a")
    assert [s[1] for s in steps[:2]] == ["helpline/HL-1.json", "helpline/HL-1.m4a"]
    kind, key, data = steps[2][1:]
    assert (kind, key, data["recording_key"]) == ("helpline", "helpline/HL-1.json", "helpline/HL-1.m4a")


def test_call_without_recording(steps):
    intake.receive_helpline_call({"report_id": "HL-2", "recording_file": None})
    assert [s[0] for s in steps] == ["save", "queue"] and "recording_key" not in steps[1][3]


def test_upload_saved_then_queued(steps):
    intake.receive_upload({"upload_id": "UP-1", "file": "report.pdf"}, "data/uploads/report.pdf")
    assert steps[0] == ("save", "uploads/UP-1/report.pdf")
    assert steps[1][3]["file_key"] == "uploads/UP-1/report.pdf"
