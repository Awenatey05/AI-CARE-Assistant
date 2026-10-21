"""The hand-typed field round, cleaned and scored with the same Python rules as Kobo."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.rag.loaders import read_excel_rows
from app.services.field_round import age, clean_row, days_missed, interview_date, sex, yes_no
from app.services.rules import indicators_from_answers

DATA = Path(__file__).resolve().parent.parent / "data"
RULE_SOURCES = {"rules", "rules_and_remark"}


@pytest.fixture(scope="module")
def children():
    rows = read_excel_rows(DATA / "uploads" / "field_round_2025_r2_west_gonja.xlsx")
    labels = json.loads((DATA / "labels.json").read_text())["UP-2026-0009"]["children"]
    by_name = {child["name"]: child for child in labels}
    return [(clean_row(row, year=2025), by_name[row["Child name"]]) for row in rows]


def test_rules_match_answer_key(children):
    """Every indicator the answer key found from the answers is found by rules.py,
    and rules.py finds nothing the answer key does not list."""
    for cleaned, label in children:
        if label["status"] != "assessed":
            continue
        found = {i for i, _ in indicators_from_answers(cleaned["answers"])}
        from_rules = {i["id"] for i in label["indicators"] if i["source"] in RULE_SOURCES}
        listed = {i["id"] for i in label["indicators"]}
        assert from_rules <= found <= listed, cleaned["name"]


def test_incomplete_rows_not_scored(children):
    for cleaned, label in children:
        assert cleaned["incomplete"] == (label["status"] == "not_scored_incomplete"), cleaned["name"]


def test_every_date_and_age_cleaned(children):
    for cleaned, label in children:
        assert cleaned["date"].startswith("2025-06-")
        assert cleaned["age"] == label["age"]
        assert cleaned["sex"] == {"M": "male", "F": "female"}.get(label["sex"], label["sex"])


@pytest.mark.parametrize("raw,clean", [("Y", "yes"), ("YES", "yes"), (" yes", "yes"), ("n", "no"),
                                       ("NO", "no"), (" No", "no"), (None, None), ("", None)])
def test_yes_no(raw, clean):
    assert yes_no(raw) == clean


def test_yes_no_rejects_other_text():
    with pytest.raises(ValueError):
        yes_no("maybe")


@pytest.mark.parametrize("raw,clean", [("14", 14), (9, 9), ("9yrs", 9), ("about 6", 6), (None, None)])
def test_age(raw, clean):
    assert age(raw) == clean


@pytest.mark.parametrize("raw", ["12 June", "12/06/2025", "12/06/25", "2025-06-12", "12 June 2025"])
def test_dates(raw):
    assert interview_date(raw, year=2025) == "2025-06-12"


def test_sex_and_days_missed():
    assert [sex(v) for v in ("M", "m", "Male", "F", "Female")] == ["male"] * 3 + ["female"] * 2
    assert [days_missed(v) for v in ("0", "2", "5", None)] == ["0", "1_3", "4_plus", None]
