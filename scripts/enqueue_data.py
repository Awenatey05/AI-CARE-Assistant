"""
LOAD THE DATA(demo note: saved Kobo submissions are replayed)

Sends the synthetic data through the same intake as real submissions:
each original is saved in storage, then a job is queued for the worker.
Cases already in the database are skipped, so running it twice does not redo work.

    data/*.json, recordings, uploads
        |
        v
    intake (save original -> queue job)
        |
        v
    worker.py (run separately) -> Postgres
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.db import connect, create_tables
from app.services import intake, queue, storage

DATA = Path("data")
SECONDS_PER_CASE = 9   # measured: the model takes about 9 seconds per case


def already_saved() -> tuple[set[str], set[str]]:
    """IDs of cases in the database, and the uploads they came from."""
    with connect() as connection:
        rows = connection.execute("SELECT id, source_id, channel FROM cases").fetchall()
    return {r["id"] for r in rows}, {r["source_id"] for r in rows if r["channel"] == "upload"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the synthetic data through intake into the queue")
    parser.add_argument("--all", action="store_true", help="everything")
    parser.add_argument("--field", type=int, default=0, help="number of field submissions (0 = none)")
    parser.add_argument("--edge", action="store_true", help="the 20 edge cases")
    parser.add_argument("--helpline", type=int, default=0, help="number of helpline calls (0 = none)")
    parser.add_argument("--uploads", action="store_true", help="the 11 uploads")
    args = parser.parse_args()

    create_tables()
    storage.ensure_bucket()
    saved, saved_uploads = already_saved()
    queued, skipped = {}, 0

    # 1. Kobo field submissions
    field = json.loads((DATA / "field_submissions.json").read_text())
    if args.all or args.field:
        for submission in field if args.all else field[:args.field]:
            if submission["case_uuid"] in saved:
                skipped += 1
                continue
            intake.receive_field_submission(submission)
            queued["field"] = queued.get("field", 0) + 1

    # 2. Edge and adversarial cases (also Kobo submissions)
    if args.all or args.edge:
        for submission in json.loads((DATA / "edge_cases.json").read_text()):
            if submission["case_uuid"] in saved:
                skipped += 1
                continue
            intake.receive_field_submission(submission)
            queued["edge"] = queued.get("edge", 0) + 1

    # 3. Helpline calls, with their recordings
    calls = json.loads((DATA / "helpline_reports.json").read_text())
    if args.all or args.helpline:
        for call in calls if args.all else calls[:args.helpline]:
            if call["report_id"] in saved:
                skipped += 1
                continue
            recording = DATA / "recordings" / call["recording_file"] if call.get("recording_file") else None
            intake.receive_helpline_call(call, recording)
            queued["helpline"] = queued.get("helpline", 0) + 1

    # 4. Uploads (documents, sheets, videos)
    if args.all or args.uploads:
        for entry in json.loads((DATA / "uploads" / "uploads_manifest.json").read_text()):
            if entry["upload_id"] in saved_uploads:
                skipped += 1
                continue
            intake.receive_upload(entry, DATA / "uploads" / entry["file"])
            queued["upload"] = queued.get("upload", 0) + 1

    total = sum(queued.values())
    print(f"Queued: {queued or 'nothing'} ({total} jobs); skipped {skipped} already in the database")
    print(f"Queue now: {queue.queue_sizes()}")
    if total:
        print(f"At about {SECONDS_PER_CASE} s per case, the worker needs roughly "
              f"{total * SECONDS_PER_CASE / 60:.0f} minutes (sheets hold several children each).")


if __name__ == "__main__":
    main()
