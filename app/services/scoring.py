"""Scoring rules (applied in Python, never by the model).

Each indicator present adds 1 point. Python counts the indicators present,
sets No risk, Low, Moderate or High, and applies the urgent flags.
The result has the same fields as labels.json.
"""

from __future__ import annotations

from typing import Any

CRITICAL_INDICATORS = {1, 2, 5, 6}

# The form requires a closing report of at least 100 characters.
MIN_CLOSING_REPORT = 100


def band(score: int, urgent: bool) -> str:
    """0 -> No risk, 1-2 -> Low, 3-5 -> Moderate, 6-10 -> High. Urgent flags make it High."""
    if urgent:
        return "High"
    if score == 0:
        return "No risk"
    if score <= 2:
        return "Low"
    if score <= 5:
        return "Moderate"
    return "High"


def rule_or_model(rule_indicators: list[tuple[int, str | None]],
                  model_indicators: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rule or model: an indicator is present if the rules OR the model finds it.

    rule_indicators: (indicator, subtype) pairs from rules.py
    model_indicators: {"id", "subtype", "quote"} from the model, already validated
    """
    found = {i: {"id": i, "subtype": s, "source": "answers"} for i, s in rule_indicators}
    for m in model_indicators:
        if m["id"] in found:
            found[m["id"]].update(source="both", quote=m["quote"])
        else:
            found[m["id"]] = {"id": m["id"], "subtype": m["subtype"], "source": "report", "quote": m["quote"]}
    return [found[i] for i in sorted(found)]


def not_scored(answers: dict[str, str]) -> str | None:
    """Return the status if the case gets no band, or None if it can be scored.

    Not scored: an incomplete submission, or an interview the caregiver refused
    or the child declined. A refused interview where the worker recorded serious
    concern or immediate danger goes to human review instead of being dropped.
    """
    refused = answers.get("caregiver_consent") == "refused" or answers.get("child_assent") == "no"
    if refused:
        if answers.get("worker_concern") in ("serious", "immediate_danger"):
            return "human_review"
        return "not_scored_no_consent"
    if len((answers.get("closing_report") or "").strip()) < MIN_CLOSING_REPORT:
        return "not_scored_incomplete"
    return None


def urgent_flags(indicators: list[dict[str, Any]], answers: dict[str, str]) -> list[str]:
    """The reasons a case is High straight away, regardless of score."""
    reasons: list[str] = []
    critical = sorted({i["id"] for i in indicators} & CRITICAL_INDICATORS)
    if critical:
        reasons.append("critical_indicator:" + ",".join(str(i) for i in critical))
    if answers.get("worker_concern") == "immediate_danger":
        reasons.append("worker_immediate_danger")
    if answers.get("self_harm_thoughts") == "yes":
        reasons.append("self_harm")
    return reasons


def case_flags(answers: dict[str, str]) -> list[str]:
    """Flags stored with the case for officers to see."""
    flags: list[str] = []
    if (answers.get("interview_language") or "").strip().lower() not in ("", "english"):
        flags.append("local_language")
    if answers.get("interview_private") not in (None, "yes"):
        flags.append("not_private")
    if answers.get("visit_type") == "followup":
        flags.append("followup")
    # "Prefers not to say" counts as answered, is never scored as "no", and marks the case for follow-up.
    if "prefers_not_to_say" in answers.values():
        flags.append("prefers_not_to_say")
    return flags


def score_without_form(indicators: list[dict[str, Any]],
                       answers: dict[str, str] | None = None) -> dict[str, Any]:
    """For helpline calls, uploaded documents and sheets: no Kobo form, so no consent or
    completeness check. Score, band and urgent flags come from the indicators found;
    answers typed into a sheet (immediate danger, self-harm) still raise urgent flags."""
    reasons = urgent_flags(indicators, answers or {})
    score = len({i["id"] for i in indicators})
    return {"status": "assessed", "indicators": indicators, "score": score,
            "band": band(score, bool(reasons)), "alert": bool(reasons),
            "urgent_reasons": reasons, "flags": []}


def score_case(answers: dict[str, str], indicators: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the result for one case: status, score, band, alert, urgent_reasons, flags."""
    result: dict[str, Any] = {"status": "assessed", "indicators": indicators, "score": None, "band": None,
                              "alert": False, "urgent_reasons": [], "flags": case_flags(answers)}

    status = not_scored(answers)
    if status == "human_review":
        concern = answers.get("worker_concern")
        result.update(status=status, indicators=[], observed_indicators=indicators,
                      alert=True, urgent_reasons=[f"refused_with_{concern}"])
        return result
    if status:
        result.update(status=status, indicators=[])
        return result

    reasons = urgent_flags(indicators, answers)
    score = len({i["id"] for i in indicators})
    result.update(score=score, band=band(score, bool(reasons)),
                  alert=bool(reasons), urgent_reasons=reasons)
    return result
