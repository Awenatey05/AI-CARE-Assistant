"""Intake: the one way into the system.

For every arriving case: save the untouched original in storage first, then
put a job in the queue. FastAPI (Kobo webhook, uploads) and the data-loading
script both use these functions, so data always enters the same way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services import queue, storage


def receive_field_submission(submission: dict[str, Any]) -> str:
    """A Kobo form: save it as received, then queue it. Returns the job ID."""
    key = storage.save_json(f"field/{submission['case_uuid']}.json", submission)
    return queue.enqueue("field", submission, original_key=key)


def receive_helpline_call(call: dict[str, Any], recording_path: str | Path | None = None) -> str:
    """A helpline call report, and its recording if the caller agreed to it."""
    data = dict(call)
    key = storage.save_json(f"helpline/{call['report_id']}.json", call)
    if recording_path:
        data["recording_key"] = storage.save_file(f"helpline/{Path(recording_path).name}", recording_path)
    return queue.enqueue("helpline", data, original_key=key)


def receive_upload(entry: dict[str, Any], file_path: str | Path) -> str:
    """An uploaded document, sheet or video, with what the upload page sent about it."""
    data = dict(entry)
    data["file_key"] = storage.save_file(f"uploads/{entry['upload_id']}/{Path(file_path).name}", file_path)
    return queue.enqueue("upload", data, original_key=data["file_key"])
