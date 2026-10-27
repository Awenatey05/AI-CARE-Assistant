"""The pipeline's logic, with a fake model, masker and Whisper (no Ollama, no spaCy, no audio).

These tests check that every case goes through the right steps in the right order;
the model's judgement is measured separately.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import pipeline


def fake_result(found=(), success=True, summary="Test summary."):
    """What assess_case() returns: found = [(indicator, subtype, quote), ...]."""
    if not success:
        return {"success": False, "error": "Invalid JSON or schema", "details": "x", "data": None}
    labels = [SimpleNamespace(id=n, present=n in {f[0] for f in found},
                              subtype=next((f[1] for f in found if f[0] == n), None),
                              quote=next((f[2] for f in found if f[0] == n), None)) for n in range(1, 11)]
    return {"success": True, "error": None, "details": None,
            "data": SimpleNamespace(indicators=labels, summary=summary)}


@pytest.fixture
def fakes(monkeypatch):
    """Replace the model, the masker and Whisper; record what the model was asked."""
    calls = {"model": [], "result": fake_result()}
    monkeypatch.setattr(pipeline, "mask", lambda text, known=None: text.replace("Ama", "[NAME]"))

    def fake_assess(case_id, report, other_answer=None):
        calls["model"].append(report)
        return calls["result"]

    monkeypatch.setattr(pipeline, "assess_case", fake_assess)
    monkeypatch.setattr(pipeline, "transcribe",
                        lambda path: calls.get("transcript", {"text": "A clear transcript.", "needs_human": False}))
    return calls


def kobo(**answers):
    base = {"interview/caregiver_consent": "yes", "interview/child_assent": "yes", "interview/region": "oti",
            "child/child_name": "Ama Mensah", "safety/hurt_by_someone": "no",
            "closing/closing_report": "Ama said she went to bed hungry. " * 5}
    base.update(answers)
    return {"case_uuid": "case-1", "_id": 1, "end": "2026-01-01T10:00:00", **base}


# ------------------------------------------------
# Kobo field submissions
# ------------------------------------------------

def test_refused_interview_is_not_scored_and_the_model_is_not_asked(fakes):
    case = pipeline.process_field_submission(kobo(**{"interview/caregiver_consent": "refused"}))
    assert case["status"] == "not_scored_no_consent" and case["band"] is None
    assert fakes["model"] == []


def test_rules_and_model_combined(fakes):
    fakes["result"] = fake_result([(3, None, "she went to bed hungry")])
    case = pipeline.process_field_submission(kobo(**{"safety/in_school": "no"}))
    assert {(i["id"], i["source"]) for i in case["indicators"]} == {(3, "report"), (7, "answers")}
    assert (case["score"], case["band"], case["region"]) == (2, "Low", "oti")


def test_the_model_reads_masked_text_and_the_name_is_kept_for_follow_up(fakes):
    case = pipeline.process_field_submission(kobo())
    assert "Ama" not in fakes["model"][0] and "[NAME]" in fakes["model"][0]
    assert case["child_name"] == "Ama Mensah" and "Ama" not in case["masked_text"]


def test_model_failure_keeps_rule_findings_and_still_alerts(fakes):
    fakes["result"] = fake_result(success=False)
    case = pipeline.process_field_submission(kobo(**{"safety/hurt_by_someone": "yes"}))
    assert case["status"] == "could_not_assess" and case["band"] is None
    assert case["alert"] and case["urgent_reasons"] == ["critical_indicator:1"]
    assert case["observed_indicators"][0]["id"] == 1


# ------------------------------------------------
# Helpline calls
# ------------------------------------------------

def test_trusted_recording_is_added_to_the_report(fakes):
    call = {"report_id": "HL-1", "region": "oti", "report_text": "Summary of the call.", "recording_file": "HL-1.m4a"}
    pipeline.process_helpline_call(call)
    assert "TRANSCRIPT OF THE CALL" in fakes["model"][0] and "A clear transcript." in fakes["model"][0]


def test_flagged_recording_is_not_read_by_the_model(fakes):
    fakes["transcript"] = {"text": "I have a very good boy.", "needs_human": True}
    call = {"report_id": "HL-1", "region": "oti", "report_text": "Summary of the call.", "recording_file": "HL-1.m4a"}
    case = pipeline.process_helpline_call(call)
    assert "very good boy" not in fakes["model"][0]
    assert "needs_transcription" in case["flags"]


def test_critical_finding_in_a_call_raises_an_alert(fakes):
    fakes["result"] = fake_result([(2, None, "an adult touches him at night")])
    case = pipeline.process_helpline_call({"report_id": "HL-1", "report_text": "x", "recording_file": None})
    assert case["band"] == "High" and case["urgent_reasons"] == ["critical_indicator:2"]


# ------------------------------------------------
# Sheets: one case per row
# ------------------------------------------------

def test_attendance_rule_needs_no_model(fakes):
    row = {"Pupil": "Ama Mensah", "Days absent (Sep)": 5, "Days absent (Oct)": 0, "Teacher remark": None}
    case = pipeline.attendance_row(row, {"id": "UP-1#1", "flags": []}, 2026)
    assert [i["id"] for i in case["indicators"]] == [7] and fakes["model"] == []


def test_attendance_below_the_limit(fakes):
    row = {"Pupil": "Ama Mensah", "Days absent (Sep)": 3, "Days absent (Oct)": 3, "Teacher remark": None}
    assert pipeline.attendance_row(row, {"id": "UP-1#1", "flags": []}, 2026)["band"] == "No risk"


def test_incomplete_field_round_row_is_not_scored(fakes):
    row = {"Child name": "Ama Mensah", "Date": "12 June", "Hurt by someone": None, "Unwanted touch": None,
           "Meals yesterday": None, "In school": None, "Birth cert": "Y"}
    case = pipeline.field_round_row(row, {"id": "UP-1#1", "flags": []}, 2025)
    assert case["status"] == "not_scored_incomplete" and fakes["model"] == []


def test_sheet_year_comes_from_its_own_dates():
    rows = [{"Date": "12 June"}, {"Date": "12/06/2025"}, {"Date": "2025-06-13"}]
    assert pipeline.sheet_year(rows, default=2026) == 2025
    assert pipeline.sheet_year([{"Pupil": "x"}], default=2026) == 2026


def test_could_not_assess_with_danger_words_raises_the_alert():
    from app.services.pipeline import could_not_assess
    failed = {"error": "invalid", "details": []}
    with_words = could_not_assess({"masked_text": "Her uncle beat her with a cable.", "flags": []}, [], {}, failed)
    assert with_words["alert"] and with_words["urgent_reasons"] == ["possible_critical_not_assessed:1"]
    without = could_not_assess({"masked_text": "The child is shy at school.", "flags": []}, [], {}, failed)
    assert not without["alert"] and without["status"] == "could_not_assess"
