"""Office intake: helpline reports and uploads, sent by the Streamlit pages.

Like the Kobo webhook, these only check the request, save the original and
queue the job, then answer straight away. They need the API key (X-Api-Key),
which only the Streamlit pages have.
"""

from __future__ import annotations

import logging
import secrets
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, status

from app.services import intake
from config import API_KEY

router = APIRouter(tags=["office"])
log = logging.getLogger("api")

# 1. WHAT IS ACCEPTED
REGIONS = {"ahafo", "ashanti", "bono", "bono_east", "central", "eastern", "greater_accra", "north_east",
           "northern", "oti", "savannah", "upper_east", "upper_west", "volta", "western", "western_north"}
AUDIO_TYPES = {".m4a", ".mp3", ".wav"}
UPLOAD_TYPES = {".pdf", ".docx", ".xlsx", ".mp4", ".mov"}
SHEET_TYPES = {"school_attendance_register", "community_committee_log", "field_round_compilation"}
MAX_MB = 100


def check_api_key(sent: str | None) -> None:
    if not API_KEY:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API key not configured")
    if not sent or not secrets.compare_digest(sent, API_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or wrong API key")


def check_region(region: str) -> str:
    region = region.strip().lower().replace(" ", "_")
    if region not in REGIONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown region: {region}")
    return region


def new_id(prefix: str) -> str:
    """HL-2026-1a2b3c4d / UP-2026-1a2b3c4d: the year and a short random part, so two offices never clash."""
    return f"{prefix}-{datetime.now(timezone.utc).year}-{uuid.uuid4().hex[:8]}"


def keep_file(upload: UploadFile, allowed: set[str], folder: str, name: str) -> Path:
    """Write an uploaded file to a temporary folder, checking its type and size."""
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"File type {suffix or '(none)'} not accepted; use {', '.join(sorted(allowed))}")
    data = upload.file.read()
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File larger than {MAX_MB} MB")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty")
    path = Path(folder) / f"{name}{suffix}"
    path.write_bytes(data)
    return path


def queue_or_503(receive, *args) -> str:
    try:
        return receive(*args)
    except HTTPException:
        raise
    except Exception as error:          # storage or queue unavailable
        log.error("office intake failed: %s", type(error).__name__)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not accept it now; try again") from error


# 2. A HELPLINE REPORT
@router.post("/helpline", status_code=status.HTTP_202_ACCEPTED)
def receive_helpline_report(
    region: Annotated[str, Form()],
    district: Annotated[str, Form()],
    report_text: Annotated[str, Form(min_length=20)],
    caller_type: Annotated[str, Form()] = "an anonymous caller",
    consent_to_record: Annotated[bool, Form()] = False,
    recording: Annotated[UploadFile | None, File()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """An officer's typed report of a call, with the recording only if the caller agreed."""
    check_api_key(x_api_key)
    report_id = new_id("HL")
    call = {"report_id": report_id, "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "channel": "helpline", "region": check_region(region), "district": district.strip(),
            "caller_type": caller_type.strip(), "consent_to_record": "yes" if consent_to_record else "no",
            "recording_file": None, "report_type": "officer_report", "report_text": report_text.strip()}

    has_recording = recording is not None and recording.filename
    if has_recording and not consent_to_record:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A recording needs the caller's consent")

    with tempfile.TemporaryDirectory() as folder:
        path = keep_file(recording, AUDIO_TYPES, folder, report_id) if has_recording else None
        if path:
            call.update(recording_file=path.name, report_type="summary_of_recorded_call")
        job_id = queue_or_503(intake.receive_helpline_call, call, path)
    log.info("helpline report %s queued as job %s", report_id, job_id[:8])
    return {"status": "queued", "report_id": report_id, "job_id": job_id}


# 3. AN UPLOADED DOCUMENT, SHEET OR VIDEO
@router.post("/uploads", status_code=status.HTTP_202_ACCEPTED)
def receive_upload(
    file: Annotated[UploadFile, File()],
    region: Annotated[str, Form()],
    district: Annotated[str, Form()],
    document_type: Annotated[str, Form()],
    child_name: Annotated[str | None, Form()] = None,
    uploaded_by_role: Annotated[str, Form()] = "office_staff",
    x_api_key: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """A document, sheet or video about one child (or, for a sheet, many)."""
    check_api_key(x_api_key)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix == ".xlsx" and document_type not in SHEET_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"A sheet must be one of: {', '.join(sorted(SHEET_TYPES))}")
    upload_id = new_id("UP")
    entry = {"upload_id": upload_id, "file_type": suffix.lstrip("."), "document_type": document_type.strip(),
             "region": check_region(region), "district": district.strip(),
             "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "uploaded_by_role": uploaded_by_role, "channel": "upload",
             "child_name": (child_name or "").strip() or None}

    with tempfile.TemporaryDirectory() as folder:
        path = keep_file(file, UPLOAD_TYPES, folder, Path(file.filename).stem)
        entry["file"] = path.name
        job_id = queue_or_503(intake.receive_upload, entry, path)
    log.info("upload %s (%s) queued as job %s", upload_id, suffix, job_id[:8])
    return {"status": "queued", "upload_id": upload_id, "job_id": job_id}
