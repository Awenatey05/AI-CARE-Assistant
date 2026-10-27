"""Python rules: reading closed (yes/no, multiple-choice) answers.

Closed answers map directly to indicators, so they are read with simple
Python rules, not by the model. Free text (the closing report and
"Other" descriptions) is left for the model.
"""

from __future__ import annotations

import re

Indicator = tuple[int, str | None]  # (indicator number, subtype "a"/"b" or None)

# Kobo puts each answer under its form group, e.g. "safety/in_school".
FORM_GROUPS = ("interview", "child", "safety", "worker", "closing")


def read_answers(submission: dict[str, str]) -> dict[str, str]:
    """Remove the group names: {"safety/in_school": "no"} becomes {"in_school": "no"}."""
    answers: dict[str, str] = {}
    for key, value in submission.items():
        group, _, field = key.partition("/")
        if field and group in FORM_GROUPS:
            answers[field] = value
    return answers


def selected(answers: dict[str, str], field: str) -> set[str]:
    """Multiple-choice answers come as one string, e.g. "cannot_pay_fees must_work"."""
    return set((answers.get(field) or "").split())


def indicators_from_answers(answers: dict[str, str]) -> list[Indicator]:
    """Return the indicators the closed answers show, as (indicator, subtype) pairs."""
    found: list[Indicator] = []

    # 1. Physical violence or injury
    if answers.get("hurt_by_someone") == "yes" or answers.get("injury_observed") == "yes":
        found.append((1, None))

    # 2. Sexual abuse or exploitation
    if answers.get("unwanted_touch") == "yes" or answers.get("exchange_for_gifts") == "yes":
        found.append((2, None))

    # 3. Neglect
    if answers.get("meals_yesterday") == "0" or answers.get("cared_for_when_sick") == "no":
        found.append((3, None))

    # 4. Child labour
    if answers.get("works_for_others") == "yes":
        found.append((4, None))

    # 5. Child marriage and harmful practices
    # "Other" on its own never triggers an indicator: the model reads the description.
    harmful = selected(answers, "harmful_practice") - {"none", "other"}
    if answers.get("married_or_promised") == "yes" or harmful:
        found.append((5, None))

    # 6. Trafficking, separated child
    if answers.get("brought_to_work") == "yes":
        found.append((6, "a"))
    elif answers.get("lives_with") in ("employer", "street", "alone"):
        found.append((6, "b"))

    # 7. Out of school
    if answers.get("in_school") == "no" or answers.get("days_missed") == "4_plus":
        found.append((7, None))

    # 8. Unsafe or absent caregiver
    if (answers.get("caregiver_home") == "no"
            or answers.get("caregiver_drinks_violent") == "yes"
            or answers.get("cares_for_siblings") == "yes"):
        found.append((8, None))

    # 9. Emotional distress
    if (answers.get("often_sad_scared") == "yes"
            or answers.get("self_harm_thoughts") == "yes"
            or answers.get("safe_at_home") == "no"):
        found.append((9, None))

    # 10. No legal identity, discrimination
    if answers.get("has_birth_certificate") == "no":
        found.append((10, "a"))
    elif answers.get("treated_differently") == "yes":
        found.append((10, "b"))

    return found


def other_answer_for_model(answers: dict[str, str]) -> str | None:
    """If the worker selected "Other" for a harmful practice, return the description for the model."""
    if "other" in selected(answers, "harmful_practice"):
        return (answers.get("harmful_other") or "").strip() or None
    return None


# DANGER WORDS IN TEXT THAT COULD NOT BE ASSESSED
# Used only when the model's answer failed twice: clear words for a critical risk
# raise the alert anyway, so a person looks at the case first. Words are matched
# in the masked text, whole words, ignoring capitals.
DANGER_WORDS = {
    "1": r"beat(en|s|ing)?|slapped|burn(ed|t)|bruis(e|es|ed)|wound(s|ed)?|injur(y|ies|ed)",
    "2": r"rap(e|ed)|defiled?|touch(ed|es) her|touch(ed|es) him|sexual",
    "5": r"marr(y|ied|iage)|betroth(ed)?|bride price|dowry|cutting|witch(craft)?",
    "6": r"traffick(ed|ing|er)|agent",
    "self_harm": r"kill (herself|himself)|end (her|his) life|hurt (herself|himself)|suicide|wants? to die",
}


def danger_words(text: str | None) -> list[str]:
    """The critical indicators (and self-harm) whose danger words appear in the text."""
    return [risk for risk, words in DANGER_WORDS.items()
            if text and re.search(rf"\b({words})\b", text, flags=re.IGNORECASE)]
