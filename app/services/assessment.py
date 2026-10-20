"""Assess one case with the model: prompt -> model -> JSON -> schema -> quote check.

Never trust model output blindly. If the answer is invalid, the model is
told what was wrong and asked once more; if it fails again, the case is
marked "could not assess" and goes to a human. It is never given a band.
"""

from __future__ import annotations

import re
from typing import Any

import requests
from pydantic import ValidationError

from app.llm.client import chat_with_llm, parse_json_object
from app.llm.prompts import SYSTEM_PROMPT
from app.models.assessment import Assessment

MAX_ATTEMPTS = 2  # first try + one retry


def normalise(text: str) -> str:
    """Collapse spaces and line breaks so a quote can be compared with the report."""
    return re.sub(r"\s+", " ", text).strip()


def quote_in_text(quote: str, text: str) -> bool:
    """A quote must appear in the text word for word (extra spaces or a missing final full stop are allowed)."""
    quote, text = normalise(quote), normalise(text)
    return quote in text or quote.rstrip(".") in text


def check_quotes(assessment: Assessment, text: str) -> list[str]:
    """Return one error for every quote that does not appear in the text."""
    return [f"the quote for indicator {label.id} is not in the report"
            for label in assessment.indicators
            if label.present and not quote_in_text(label.quote, text)]


def present_indicators(assessment: Assessment) -> list[dict[str, Any]]:
    """The present indicators, in the form scoring.rule_or_model() expects."""
    return [{"id": label.id, "subtype": label.subtype, "quote": label.quote}
            for label in assessment.indicators if label.present]


def assess_case(case_id: str, report: str, other_answer: str | None = None,
                system_prompt: str = SYSTEM_PROMPT, model: str | None = None) -> dict[str, Any]:
    """Ask the model to label the 10 indicators for one case and validate the answer.

    Returns {"success", "error", "details", "data", "attempts", "latency_s"}.
    On success, "data" is the validated Assessment.
    """
    # 1. Messages: the assessor's rules (system) and this case's report (user).
    user_prompt = f"CASE ID: {case_id}\n\nREPORT:\n{report.strip()}\n"
    if other_answer:
        user_prompt += f"\nOTHER HARMFUL PRACTICE (described by the field worker):\n{other_answer.strip()}\n"

    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt},
    ]

    # Quotes may come from the report or from the "Other" description.
    source_text = report + "\n" + (other_answer or "")
    latency = 0.0
    error, details = None, None

    for attempt in range(1, MAX_ATTEMPTS + 1):

        # 2. Call the model.
        try:
            generation = chat_with_llm(messages, model=model, format="json")
        except requests.exceptions.RequestException as exc:
            error, details = "Model unavailable", str(exc)
            continue
        latency += generation.latency_s

        # 3. Parse and validate.
        try:
            assessment = Assessment.model_validate(parse_json_object(generation.text))
        except (ValueError, ValidationError) as exc:
            error, details = "Invalid JSON or schema", str(exc)
        else:
            # 4. Every quote must really be in the report.
            quote_errors = check_quotes(assessment, source_text)
            if not quote_errors:
                # The case ID is ours, not the model's.
                assessment.case_id = case_id
                return {"success": True, "error": None, "details": None, "data": assessment,
                        "attempts": attempt, "latency_s": round(latency, 2)}
            error, details = "Quote not in report", quote_errors

        # 5. Retry once: tell the model what was wrong.
        messages = messages + [
            {"role": "assistant", "content": generation.text},
            {"role": "user", "content": f"Your answer was not valid: {details}. "
                                        "Return the corrected JSON only."},
        ]

    # 6. Failed twice: could not assess. A human reviews the case.
    return {"success": False, "error": error, "details": details, "data": None,
            "attempts": MAX_ATTEMPTS, "latency_s": round(latency, 2)}
