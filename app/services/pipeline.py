"""The pipeline: everything that happens to one case.

One function per way a case arrives (Kobo form, helpline call, uploaded file).
Each runs the same steps with code from the earlier stages and returns the
finished case record, ready for case_store.save_case(). Nothing here talks
to the model or the database directly.
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.rag.loaders import read_document, read_excel_rows
from app.services import storage
from app.services.assessment import assess_case, present_indicators
from collections import Counter

from app.services.field_round import clean_row, interview_date
from app.services.masking import mask
from app.services.rules import danger_words, indicators_from_answers, other_answer_for_model, read_answers
from app.services.scoring import (not_scored, rule_or_model, score_case, score_without_form,
                                  urgent_flags)
from app.services.transcription import transcribe

DOCUMENT_TYPES = {".pdf", ".docx"}
VIDEO_TYPES = {".mp4", ".mov"}
SHEET_TYPES = {".xlsx"}
DAYS_ABSENT_LIMIT = 4   # 4 or more school days missed in a month -> indicator 7


# 1. SHARED STEP: MASK, THEN ASK THE MODEL
def model_indicators(case_id: str, text: str, known_names: list[str],
                     other_answer: str | None = None) -> tuple[dict[str, Any], str]:
    """Mask names and phone numbers, then label the indicators with the model.

    Returns the assess_case() result and the masked text (stored with the case).
    """
    masked = mask(text, known_names)
    masked_other = mask(other_answer, known_names) if other_answer else None
    result = assess_case(case_id, masked, masked_other)
    return result, masked


def could_not_assess(base: dict[str, Any], rule_found: list[dict[str, Any]],
                     answers: dict[str, str], result: dict[str, Any]) -> dict[str, Any]:
    """The model failed twice: no band, a person reviews the case.

    Indicators already found by the Python rules are kept as observed, and if they
    (or the worker's answers) are urgent, the alert is still raised: a model failure
    must never hide a child in danger. Clear danger words in the text raise it too.
    """
    reasons = urgent_flags(rule_found, answers)
    words = danger_words(base.get("masked_text"))
    if words:
        reasons = reasons + [f"possible_critical_not_assessed:{','.join(words)}"]
    return {**base, "status": "could_not_assess", "score": None, "band": None,
            "indicators": [], "observed_indicators": rule_found,
            "alert": bool(reasons), "urgent_reasons": reasons,
            "flags": base.get("flags", []) + [f"model_failed: {result['error']}"]}


@contextmanager
def local_copy(key: str | None, fallback: Path):
    """The file to process: a temporary copy of the original in storage (deleted
    afterwards), or the local file when the job names no stored original."""
    if not key:
        yield fallback
        return
    with tempfile.TemporaryDirectory() as folder:
        yield storage.download_to(key, folder)


# 2. A KOBO FIELD SUBMISSION
def process_field_submission(submission: dict[str, Any], original_key: str | None = None) -> dict[str, Any]:
    answers = read_answers(submission)
    case_id = submission["case_uuid"]
    child_name = answers.get("child_name")
    base = {"id": case_id, "channel": "field", "source_id": str(submission.get("_id", case_id)),
            "region": answers.get("region"), "district": answers.get("district"),
            "community": answers.get("community"), "child_name": child_name,
            "received_at": submission.get("end"), "original_key": original_key}

    status = not_scored(answers)
    if status and status != "human_review":
        # Refused, declined or incomplete: recorded, but not scored.
        return {**base, **score_case(answers, [])}

    rule_found = [{"id": i, "subtype": s, "source": "answers"} for i, s in indicators_from_answers(answers)]
    result, masked = model_indicators(case_id, answers.get("closing_report", ""),
                                      [child_name] if child_name else [], other_answer_for_model(answers))
    base["masked_text"] = masked
    if not result["success"]:
        return could_not_assess({**base, **score_case(answers, [])}, rule_found, answers, result)

    base["summary"] = result["data"].summary
    combined = rule_or_model([(i["id"], i["subtype"]) for i in rule_found], present_indicators(result["data"]))
    return {**base, **score_case(answers, combined)}


# 3. A HELPLINE CALL
def process_helpline_call(call: dict[str, Any], recordings_dir: str | Path = "data/recordings",
                          original_key: str | None = None) -> dict[str, Any]:
    case_id = call["report_id"]
    base = {"id": case_id, "channel": "helpline", "source_id": case_id,
            "region": call.get("region"), "district": call.get("district"),
            "received_at": call.get("received_at"), "original_key": original_key}

    text, flags = call["report_text"], []
    if call.get("recording_file"):
        with local_copy(call.get("recording_key"), Path(recordings_dir) / call["recording_file"]) as recording:
            heard = transcribe(recording)
        if heard["needs_human"]:
            flags.append("needs_transcription")      # assessed from the officer's summary only
        else:
            text = f"{text}\n\nTRANSCRIPT OF THE CALL:\n{heard['text']}"
    return assess_text(case_id, text, [], {**base, "flags": flags})


# 4. AN UPLOADED DOCUMENT OR VIDEO
def process_upload(entry: dict[str, Any], uploads_dir: str | Path = "data/uploads",
                   original_key: str | None = None) -> list[dict[str, Any]]:
    """Returns a list, because a sheet can hold many children (one case per row)."""
    with local_copy(entry.get("file_key"), Path(uploads_dir) / entry["file"]) as path:
        return process_upload_file(entry, path, original_key)


def process_upload_file(entry: dict[str, Any], path: Path, original_key: str | None) -> list[dict[str, Any]]:
    child_name = entry.get("child_name")
    base = {"id": entry["upload_id"], "channel": "upload", "source_id": entry["upload_id"],
            "region": entry.get("region"), "district": entry.get("district"),
            "child_name": child_name, "received_at": entry.get("uploaded_at"),
            "original_key": original_key}

    if path.suffix.lower() in DOCUMENT_TYPES:
        text, flags = read_document(path), []
    elif path.suffix.lower() in SHEET_TYPES:
        return process_sheet(entry, path, original_key)
    elif path.suffix.lower() in VIDEO_TYPES:
        heard = transcribe(path)
        if heard["needs_human"]:
            return [{**base, "status": "needs_transcription", "flags": ["needs_transcription"]}]
        text, flags = heard["text"], []
    else:
        raise ValueError(f"No pipeline for {entry['file']} yet")

    return [assess_text(entry["upload_id"], text, [child_name] if child_name else [], {**base, "flags": flags})]


# 5. SHARED STEP FOR TEXT WITHOUT A FORM
def assess_text(case_id: str, text: str, known_names: list[str], base: dict[str, Any]) -> dict[str, Any]:
    """Helpline calls and documents: mask, model, then score without form answers."""
    result, masked = model_indicators(case_id, text, known_names)
    base["masked_text"] = masked
    if not result["success"]:
        return could_not_assess(base, [], {}, result)
    found = [{**i, "source": "report"} for i in present_indicators(result["data"])]
    scored = score_without_form(found)
    return {**base, "summary": result["data"].summary, **scored, "flags": base["flags"] + scored["flags"]}


# 6. A SHEET: ONE CASE PER ROW
def process_sheet(entry: dict[str, Any], path: Path, original_key: str | None = None) -> list[dict[str, Any]]:
    """Attendance register, committee log or hand-typed field round: each row is one child."""
    handlers = {"school_attendance_register": attendance_row,
                "community_committee_log": committee_row,
                "field_round_compilation": field_round_row}
    handler = handlers.get(entry.get("document_type"))
    if handler is None:
        raise ValueError(f"No pipeline for sheets of type {entry.get('document_type')!r}")

    rows = read_excel_rows(path)
    year = sheet_year(rows, default=int(entry.get("uploaded_at", "2026")[:4]))
    cases = []
    for number, row in enumerate(rows, start=1):
        base = {"id": f"{entry['upload_id']}#{number}", "channel": "upload", "source_id": entry["upload_id"],
                "region": entry.get("region"), "district": entry.get("district"),
                "received_at": entry.get("uploaded_at"), "original_key": original_key, "flags": []}
        cases.append(handler(row, base, year))
    return cases


def sheet_year(rows: list[dict[str, Any]], default: int) -> int:
    """The year most of the sheet's dates are in. A date typed without a year
    ("12 June") belongs to the same round, not to the year the sheet was uploaded."""
    placeholder = 1900   # given to dates without a year, then ignored
    dates = [interview_date(row.get("Date"), year=placeholder) for row in rows if row.get("Date")]
    years = [int(d[:4]) for d in dates if d and int(d[:4]) != placeholder]
    return Counter(years).most_common(1)[0][0] if years else default


def sheet_case(base: dict[str, Any], rule_found: list[dict[str, Any]], text: str | None,
               answers: dict[str, str] | None = None) -> dict[str, Any]:
    """Rules first; the model reads the row's free text only if there is some."""
    if not text:
        return {**base, **score_without_form(rule_found, answers)}
    known = [base["child_name"]] if base.get("child_name") else []
    result, masked = model_indicators(base["id"], text, known)
    base["masked_text"] = masked
    if not result["success"]:
        return could_not_assess({**base, "flags": base["flags"]}, rule_found, answers or {}, result)
    combined = rule_or_model([(i["id"], i["subtype"]) for i in rule_found], present_indicators(result["data"]))
    return {**base, "summary": result["data"].summary, **score_without_form(combined, answers)}


def attendance_row(row: dict[str, Any], base: dict[str, Any], year: int) -> dict[str, Any]:
    """Indicator 7 is a numeric rule (4 or more days absent in a month); the teacher's remark goes to the model."""
    base["child_name"] = row.get("Pupil")
    absences = [row[c] for c in row if str(c).startswith("Days absent") and isinstance(row[c], (int, float))]
    rule_found = [{"id": 7, "subtype": None, "source": "answers"}] if any(d >= DAYS_ABSENT_LIMIT for d in absences) else []
    return sheet_case(base, rule_found, row.get("Teacher remark"))


def committee_row(row: dict[str, Any], base: dict[str, Any], year: int) -> dict[str, Any]:
    """Each concern is free text, so the model reads it."""
    base.update(child_name=row.get("Child"), community=row.get("Community"))
    return sheet_case(base, [], row.get("Concern reported"))


def field_round_row(row: dict[str, Any], base: dict[str, Any], year: int) -> dict[str, Any]:
    """Cleaned into questionnaire answers, scored with the same Python rules as Kobo."""
    cleaned = clean_row(row, year=year)
    base.update(child_name=cleaned["name"], community=cleaned["community"])
    if cleaned["incomplete"]:
        return {**base, "status": "not_scored_incomplete", "flags": ["incomplete_record"]}
    rule_found = [{"id": i, "subtype": s, "source": "answers"} for i, s in indicators_from_answers(cleaned["answers"])]
    return sheet_case(base, rule_found, cleaned["remark"], cleaned["answers"])
