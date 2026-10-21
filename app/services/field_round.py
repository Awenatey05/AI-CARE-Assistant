"""Cleaning a field round that was typed into Excel by hand (the manual step the app replaces).

Each row is cleaned into the same answers a KoboToolbox submission gives
(e.g. "Birth cert: Y" becomes has_birth_certificate = "yes"), so the same
Python rules (app/services/rules.py) can be applied to old and new data.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

# 1. COLUMNS AND VALUES
# Excel column -> questionnaire field (same names as the Kobo form).
YES_NO_COLUMNS = {
    "Birth cert": "has_birth_certificate",
    "Hurt by someone": "hurt_by_someone",
    "Injury seen": "injury_observed",
    "Unwanted touch": "unwanted_touch",
    "Cared for when sick": "cared_for_when_sick",
    "Works for others": "works_for_others",
    "In school": "in_school",
    "Caregiver home most days": "caregiver_home",
    "Caregiver drinks/violent": "caregiver_drinks_violent",
    "Often sad/scared": "often_sad_scared",
    "Feels safe at home": "safe_at_home",
    "Wanted to hurt self": "self_harm_thoughts",
    "Married/promised": "married_or_promised",
    "Brought from elsewhere to work": "brought_to_work",
    "Treated worse than others": "treated_differently",
}
LIVES_WITH = {"both parents": "both_parents", "mother only": "mother_only", "father only": "father_only",
              "grandparent": "grandparent", "aunt": "other_relative", "uncle": "other_relative",
              "employer": "employer", "alone": "alone", "street": "street"}
WORKER_CONCERN = {"none": "none", "some": "some", "serious": "serious", "immediate danger": "immediate_danger"}
COMMUNITY_SPELLING = {"Damango": "Damongo", "Laribanga": "Larabanga"}

# Blank because the question was skipped (no work, not in school), not because it is missing.
SKIPPED_WHEN_NOT_RELEVANT = {"Type of work", "Days missed last month", "Remarks"}
MAX_BLANK_ANSWERS = 2   # a row with 3 or more blank answers is not scored


# 2. CLEAN ONE VALUE
def yes_no(value: Any) -> str | None:
    """'Y', 'YES', ' yes', 'n', 'NO' -> 'yes' / 'no'. Blank -> None (not recorded)."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().lower()
    if text in ("y", "yes"):
        return "yes"
    if text in ("n", "no"):
        return "no"
    raise ValueError(f"Not a yes/no answer: {value!r}")


def age(value: Any) -> int | None:
    """'14', 14, '9yrs', 'about 6' -> the whole number of years."""
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else None


def sex(value: Any) -> str | None:
    """'M', 'm', 'Male' -> 'male'; 'F', 'f', 'Female' -> 'female'."""
    text = str(value or "").strip().lower()
    return {"m": "male", "male": "male", "f": "female", "female": "female"}.get(text)


DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d %B %Y"]


def interview_date(value: Any, year: int) -> str | None:
    """'12 June', '12/06/2025', '14/06/25', '2025-06-12' -> '2025-06-12'.
    A date without a year ('12 June') takes the year of the field round."""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip()
    if re.fullmatch(r"\d{1,2} [A-Za-z]+", text):    # day and month only
        text = f"{text} {year}"
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def days_missed(value: Any) -> str | None:
    """Number of school days missed -> the questionnaire's choice ('0', '1_3', '4_plus')."""
    days = age(value)   # same "find the number" logic
    if days is None:
        return None
    return "0" if days == 0 else "1_3" if days <= 3 else "4_plus"


# 3. CLEAN ONE ROW
def clean_row(row: dict[str, Any], year: int) -> dict[str, Any]:
    """Turn one typed Excel row into the child's details and questionnaire answers."""
    answers: dict[str, str] = {}
    for column, field in YES_NO_COLUMNS.items():
        value = yes_no(row.get(column))
        if value is not None:
            answers[field] = value

    lives_with = LIVES_WITH.get(str(row.get("Lives with") or "").strip().lower())
    if lives_with:
        answers["lives_with"] = lives_with
    if row.get("Meals yesterday") not in (None, ""):
        meals = age(row["Meals yesterday"])
        answers["meals_yesterday"] = "3_plus" if meals >= 3 else str(meals)
    if days_missed(row.get("Days missed last month")):
        answers["days_missed"] = days_missed(row["Days missed last month"])
    concern = WORKER_CONCERN.get(str(row.get("Worker concern") or "").strip().lower())
    if concern:
        answers["worker_concern"] = concern

    blank = [column for column, value in row.items()
             if column not in SKIPPED_WHEN_NOT_RELEVANT and value in (None, "")]
    community = str(row.get("Community") or "").strip()

    return {
        "name": row.get("Child name"),
        "date": interview_date(row.get("Date"), year),
        "community": COMMUNITY_SPELLING.get(community, community),
        "age": age(row.get("Age")),
        "sex": sex(row.get("Sex")),
        "answers": answers,
        "remark": (row.get("Remarks") or "").strip() or None,   # free text: read by the model
        "blank_answers": blank,
        "incomplete": len(blank) > MAX_BLANK_ANSWERS,
    }
