"""
REASSESS CASES AFTER A CHANGE TO THE ASSESSMENT

Puts cases through the worker again, from their originals in storage (never
changed), so a change to the rules or checks applies to them too:
    - every case that could not be assessed (the danger-word safety net);
    - every case where the model gave indicator 6 (trafficking) with a quote about a
      birth certificate or registration (the indicator 6 check).
A sheet is reassessed as a whole. The worker must be running; saving a case again
replaces its assessment, and its case reference stays the same.

    cases in Postgres -> originals in storage -> Redis queue -> worker.py
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.db import connect
from app.services import queue, storage

MANIFEST = Path("data/uploads/uploads_manifest.json")

TO_REASSESS = """
    SELECT DISTINCT c.channel, c.source_id, c.original_key FROM cases c
    WHERE c.original_key IS NOT NULL AND (
        c.status = 'could_not_assess'
        OR EXISTS (SELECT 1 FROM indicators i WHERE i.case_id = c.id AND i.indicator = 6 AND NOT i.observed
                   AND i.quote ~* '(birth certificate|regist)'
                   AND i.quote !~* '(agent|brought|employer|street|alone|sent to work|taken to)'))
"""


def main() -> None:
    manifest = {entry["upload_id"]: entry for entry in json.loads(MANIFEST.read_text())}
    with connect() as connection:
        cases = connection.execute(TO_REASSESS).fetchall()
    queued, skipped = {"field": 0, "helpline": 0, "upload": 0}, 0
    for case in cases:
        key = case["original_key"]
        if case["channel"] == "field":
            queue.enqueue("field", storage.read_json(key), original_key=key)
        elif case["channel"] == "helpline":
            call = storage.read_json(key)
            if call.get("recording_file"):
                call["recording_key"] = f"{Path(key).parent}/{call['recording_file']}"
            queue.enqueue("helpline", call, original_key=key)
        elif case["source_id"] in manifest:
            queue.enqueue("upload", {**manifest[case["source_id"]], "file_key": key}, original_key=key)
        else:
            skipped += 1                       # an upload sent through the page: its form is not kept
            continue
        queued[case["channel"]] += 1
    print(f"Queued again: {queued} ({sum(queued.values())} jobs); skipped {skipped}")
    print(f"Queue now: {queue.queue_sizes()}")


if __name__ == "__main__":
    main()
