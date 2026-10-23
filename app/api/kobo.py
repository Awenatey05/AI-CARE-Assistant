"""The Kobo webhook: KoboToolbox sends each submission here when an iPad syncs.

The API only checks that the submission is genuine and well formed, saves the
original and queues the job, then answers straight away (202 Accepted). The
slow work (rules, Whisper, masking, the model) happens later in the worker.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, status

from app.services import intake
from config import KOBO_WEBHOOK_SECRET

router = APIRouter(tags=["intake"])
log = logging.getLogger("api")


def check_secret(sent: str | None) -> None:
    """The submission is genuine only if it carries the shared secret set in Kobo and in .env."""
    if not KOBO_WEBHOOK_SECRET:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Webhook secret not configured")
    if not sent or not secrets.compare_digest(sent, KOBO_WEBHOOK_SECRET):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or wrong webhook secret")


@router.post("/kobo", status_code=status.HTTP_202_ACCEPTED)
def receive_kobo_submission(submission: dict[str, Any] = Body(...),
                            x_webhook_secret: str | None = Header(default=None)) -> dict[str, str]:
    """Receive one Kobo submission: check it, save the original, queue the job."""
    check_secret(x_webhook_secret)
    case_uuid = submission.get("case_uuid")
    if not isinstance(case_uuid, str) or not case_uuid.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Submission has no case_uuid")
    try:
        job_id = intake.receive_field_submission(submission)
    except Exception as error:          # storage or queue unavailable: Kobo will retry later
        log.error("Kobo submission %s could not be accepted: %s", case_uuid[:8], type(error).__name__)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not accept the submission now") from error
    log.info("Kobo submission %s queued as job %s", case_uuid[:8], job_id[:8])
    return {"status": "queued", "job_id": job_id}
