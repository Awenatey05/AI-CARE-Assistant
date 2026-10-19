"""Independent check: re-applying the questionnaire rules to the raw answers
reproduces every rule-based label in the answer key (data/labels.json)."""

import json
from pathlib import Path

import pytest

from app.services.rules import indicators_from_answers, other_answer_for_model, read_answers
from app.services.scoring import band, score_case

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def cases():
    labels = json.loads((DATA / "labels.json").read_text())
    submissions = (json.loads((DATA / "field_submissions.json").read_text())
                   + json.loads((DATA / "edge_cases.json").read_text()))
    return [(read_answers(s), labels[s["case_uuid"]]) for s in submissions]


def test_python_rules_match_answer_key(cases):
    """Indicators found in the answers must match the answer key's "answers" and "both" labels."""
    wrong = []
    for answers, label in cases:
        if label["status"] != "assessed":
            continue
        expected = {(i["id"], i["subtype"]) for i in label["indicators"] if i["source"] in ("answers", "both")}
        if set(indicators_from_answers(answers)) != expected:
            wrong.append(label["id"])
    assert not wrong, wrong[:5]


def test_scoring_rules_match_answer_key(cases):
    """Given the answer key's indicators, Python must give the same status, score, band, alert and flags."""
    for answers, label in cases:
        indicators = label["indicators"] or label.get("observed_indicators", [])
        result = score_case(answers, indicators)
        for field in ("status", "score", "band", "alert", "urgent_reasons"):
            assert result[field] == label[field], (label["id"], field)
        assert sorted(result["flags"]) == sorted(label["flags"]), label["id"]


def test_other_on_its_own_never_triggers_an_indicator():
    answers = {"harmful_practice": "other", "harmful_other": "Naming ceremony for a new baby in the family"}
    assert (5, None) not in indicators_from_answers(answers)
    assert other_answer_for_model(answers) == "Naming ceremony for a new baby in the family"


@pytest.mark.parametrize("score,urgent,expected", [
    (0, False, "No risk"), (1, False, "Low"), (2, False, "Low"), (3, False, "Moderate"),
    (5, False, "Moderate"), (6, False, "High"), (10, False, "High"), (1, True, "High"),
])
def test_band(score, urgent, expected):
    assert band(score, urgent) == expected
