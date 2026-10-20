"""The schema must reject malformed or incomplete model output instead of trusting it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.assessment import Assessment, IndicatorLabel

QUOTE = "He said his stepmother hit him with a stick last week."


def labels(ids, present=()):
    """Build indicator labels: the ids in `present` get a quote, the rest are not present."""
    return [{"id": i, "present": i in present, **({"quote": QUOTE} if i in present else {})}
            for i in ids]


# ------------------------------------------------
# IndicatorLabel: one indicator
# ------------------------------------------------

@pytest.mark.parametrize("data", [
    {"id": 1, "present": True, "quote": QUOTE},
    {"id": 2, "present": False},
    {"id": 2, "present": False, "quote": "  "},             # empty quote counts as no quote
    {"id": 6, "present": True, "subtype": "a", "quote": QUOTE},
    {"id": 10, "present": True, "subtype": "b", "quote": QUOTE},
])
def test_valid_label_accepted(data):
    IndicatorLabel.model_validate(data)


@pytest.mark.parametrize("data", [
    {"id": 11, "present": True, "quote": QUOTE},             # IDs 1-10 only
    {"id": 1, "present": "maybe"},                           # present must be true/false
    {"id": 1, "present": True},                              # present but no quote
    {"id": 2, "present": False, "quote": QUOTE},             # not present but has a quote
    {"id": 6, "present": True, "quote": QUOTE},              # 6 needs subtype a or b
    {"id": 6, "present": True, "subtype": "c", "quote": QUOTE},
    {"id": 1, "present": True, "subtype": "a", "quote": QUOTE},  # subtype only for 6 and 10
])
def test_invalid_label_rejected(data):
    with pytest.raises(ValidationError):
        IndicatorLabel.model_validate(data)


# ------------------------------------------------
# Assessment: the model's full answer
# ------------------------------------------------

def test_valid_assessment_accepted_and_sorted():
    a = Assessment.model_validate({"case_id": "c1",
                                   "indicators": labels([3, 1, 2, 4, 5, 6, 7, 8, 9, 10], {1}),
                                   "summary": "Physical violence reported."})
    assert [label.id for label in a.indicators] == list(range(1, 11))
    assert a.indicators[0].present and a.indicators[0].quote == QUOTE


def test_summary_is_optional():
    assert Assessment.model_validate({"case_id": "c1", "indicators": labels(range(1, 11))}).summary == ""


@pytest.mark.parametrize("data", [
    {"case_id": "c1", "indicators": labels(range(1, 10))},                     # only 9
    {"case_id": "c1", "indicators": labels([1, 2, 3, 4, 4, 5, 6, 7, 8, 9, 10])},  # duplicate
    {"case_id": "c1", "indicators": labels(range(1, 10)) + [{"id": 10, "present": True}]},  # bad label
    {"indicators": labels(range(1, 11))},                                      # no case_id
])
def test_invalid_assessment_rejected(data):
    with pytest.raises(ValidationError):
        Assessment.model_validate(data)


def test_broken_json_rejected():
    with pytest.raises(ValidationError):
        Assessment.model_validate_json('{"case_id": "c1", "indicators": [')
