"""Assess one case with the model: prompt -> model -> JSON -> schema -> quote check.

Never trust model output blindly. If the answer is invalid, the model is
told what was wrong and asked once more; if it fails again, the case is
marked "could not assess" and goes to a human. It is never given a band.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import requests
from pydantic import ValidationError

from app.llm.client import chat_with_llm, parse_json_object
from app.llm.prompts import SYSTEM_PROMPT
from app.models.assessment import Assessment

MAX_ATTEMPTS = 2  # first try + one retry


def normalise(text: str) -> str:
    """Collapse spaces and line breaks, and ignore upper/lower case, so a quote can be
    compared with the report ("injuries are..." matches "Injuries are...")."""
    return re.sub(r"\s+", " ", text).strip().casefold()


def quote_in_text(quote: str, text: str) -> bool:
    """A quote must appear in the text word for word (extra spaces, a different capital
    letter or a missing final full stop are allowed)."""
    quote, text = normalise(quote), normalise(text)
    return quote in text or quote.rstrip(".") in text


MAX_SAME_QUOTE = 3   # one sentence can show up to three risks, e.g. labour, trafficking and out of school


def check_quotes(assessment: Assessment, text: str) -> list[str]:
    """Return one error for every quote that does not appear in the text, and for a
    sentence given as the quote for more than MAX_SAME_QUOTE indicators."""
    present = [label for label in assessment.indicators if label.present]
    problems = [f"the quote for indicator {label.id} is not in the report"
                for label in present if not quote_in_text(label.quote, text)]
    counts = Counter(normalise(label.quote) for label in present if label.quote)
    problems += [f"the same sentence is given as the quote for {n} indicators: one sentence cannot prove that many risks"
                 for n in counts.values() if n > MAX_SAME_QUOTE]
    return problems


# A missing birth certificate is indicator 10 (no legal identity), not trafficking.
NOT_TRAFFICKING = re.compile(r"birth certificate|regist(er|ered|ration)", re.IGNORECASE)
TRAFFICKING_WORDS = re.compile(r"agent|brought|employer|street|alone|sent to work|taken to", re.IGNORECASE)


def present_indicators(assessment: Assessment) -> list[dict[str, Any]]:
    """The present indicators, in the form scoring.rule_or_model() expects. Indicator 6
    is left out when its quote is only about a birth certificate or registration."""
    return [{"id": label.id, "subtype": label.subtype, "quote": label.quote}
            for label in assessment.indicators if label.present
            and not (label.id == 6 and NOT_TRAFFICKING.search(label.quote or "")
                     and not TRAFFICKING_WORDS.search(label.quote or ""))]


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
