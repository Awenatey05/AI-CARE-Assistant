"""Cases for the dashboard: the region's figures, one case, and its original.

The figures come from the case tools (the assessment stored at intake), so the
dashboard and the chat always agree. The original is the submission exactly as
it arrived (from storage): the only place where staff see a child's name,
a phone number, a recording or a video. Every route needs the API key; with a
region, only that region's cases are shown (none = the super administrator).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import Response

from app.api.office import check_api_key, check_region
from app.core.db import connect
from app.services import storage
from app.tools.case_tools import count_cases, list_cases, show_case

router = APIRouter(tags=["cases"])

MEDIA_TYPES = {".json": "application/json", ".pdf": "application/pdf", ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
               ".wav": "audio/wav", ".mp4": "video/mp4", ".mov": "video/quicktime",
               ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
FOLLOW_UP = ["not_scored_incomplete", "human_review", "not_scored_no_consent"]


def user_region(region: str | None) -> str | None:
    return check_region(region) if region else None


# 1. THE DASHBOARD
@router.get("/dashboard")
def dashboard(region: str | None = None, x_api_key: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    """The region's figures: cases by band and by place, cases to follow up, the last Kobo submission."""
    check_api_key(x_api_key)
    region = user_region(region)
    place = "region" if region is None else "community"
    with connect() as connection:
        last_kobo = connection.execute(
            "SELECT max(received_at) AS last FROM cases WHERE channel = 'field'"
            + (" AND region = %s" if region else ""), (region,) if region else ()).fetchone()["last"]
    return {
        "region": region or "all regions",
        "by_band": count_cases(region, count_by="band"),
        "by_place": count_cases(region, count_by=place),
        "could_not_assess": count_cases(region, status="could_not_assess")["total_cases"],
        "kobo_follow_up": [case for status_ in FOLLOW_UP
                           for case in list_cases(region, limit=25, channel="field", status=status_)["cases"]],
        "last_kobo_submission": last_kobo,
    }


# 2. ONE CASE
@router.get("/cases/{case_ref}")
def one_case(case_ref: str, region: str | None = None,
             x_api_key: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    """The stored assessment of one case: band, reasons, indicators with quotes, alerts."""
    check_api_key(x_api_key)
    case = show_case(user_region(region), case_ref)
    if not case["found"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No case with this reference in your region")
    return case


# 3. THE ORIGINAL
@router.get("/cases/{case_ref}/original")
def original(case_ref: str, region: str | None = None, recording: bool = False,
             x_api_key: Annotated[str | None, Header()] = None) -> Response:
    """The submission as it arrived, or (recording=true) the call's recording, for staff to open."""
    check_api_key(x_api_key)
    region = user_region(region)
    with connect() as connection:
        case = connection.execute("SELECT region, original_key FROM cases WHERE case_ref = %s",
                                  (case_ref.strip().upper(),)).fetchone()
    if case is None or (region and case["region"] != region) or not case["original_key"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No original for this reference in your region")
    key = case["original_key"]
    if recording:
        name = storage.read_json(key).get("recording_file") if key.endswith(".json") else None   # calls only
        if not name:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "This case has no recording")
        key = f"{Path(key).parent}/{name}"
    data = storage.read_bytes(key)
    return Response(data, media_type=MEDIA_TYPES.get(Path(key).suffix.lower(), "application/octet-stream"))
