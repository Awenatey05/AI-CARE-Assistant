"""
COMPARE PROMPTS (exam Q3)

The same reports are given to SYSTEM_PROMPT, PROMPT_A, PROMPT_B and PROMPT_C.
Only the prompt changes: same report, same model, same temperature.
Each prompt gets one call (no retry), so its real behaviour is visible.

Run from the project folder:
    python -m scripts.compare_prompts
"""

from __future__ import annotations

from pydantic import ValidationError

from app.llm.client import chat_with_llm, parse_json_object
from app.llm.prompts import PROMPT_A, PROMPT_B, PROMPT_C, SYSTEM_PROMPT
from app.models.assessment import Assessment
from app.services.assessment import check_quotes

PROMPTS = {"SYSTEM_PROMPT": SYSTEM_PROMPT, "PROMPT_A": PROMPT_A,
           "PROMPT_B": PROMPT_B, "PROMPT_C": PROMPT_C}

# Short reports from the dev data, with what the answer key expects.
REPORTS = [
    ("He has no birth certificate and the family never registered his birth. The caregiver was "
     "drunk during the visit and shouted at the child throughout. He lives with his aunt in town so "
     "that he can attend a better school, and he visits his parents during holidays.",
     "8 Unsafe or absent caregiver, 10a No legal identity (living with the aunt is NOT trafficking)"),

    ("The child showed fresh marks on her arms and said her uncle beats her with a belt when she "
     "comes home late. The child said there was no food in the house yesterday and she went to bed hungry.",
     "1 Physical violence or injury, 3 Neglect"),

    ("The compound was clean and the children were playing outside. She attends the basic school in "
     "the community. She was shy at first but relaxed and laughed later in the interview.",
     "No indicators (being shy is NOT emotional distress)"),
]


def run_prompt(system_prompt: str, report: str) -> str:
    """Send one report with one system prompt; describe what came back."""
    response = chat_with_llm(
        messages=[
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": f"CASE ID: test\n\nREPORT:\n{report}"},
        ],
        format="json",
    )

    try:
        assessment = Assessment.model_validate(parse_json_object(response.text))
    except (ValueError, ValidationError) as error:
        first_error = str(error).splitlines()[:3]
        return (f"INVALID: {' '.join(first_error)}\n"
                f"Raw answer: {response.text[:250]}...")

    lines = []
    for label in assessment.indicators:
        if label.present:
            lines.append(f"{label.id}{label.subtype or ''}: \"{label.quote}\"")
    for problem in check_quotes(assessment, report):
        lines.append(f"QUOTE PROBLEM: {problem}")
    lines.append(f"Summary: {assessment.summary}")
    return "\n".join(lines) if len(lines) > 1 else "No indicators found.\n" + lines[0]


def compare(number: int) -> None:
    """Run one of the REPORTS (1, 2 or 3) through all four prompts and print the answers."""
    report, expected = REPORTS[number - 1]
    print("=" * 70)
    print(f"REPORT {number}: {report}")
    print(f"EXPECTED: {expected}")
    print("=" * 70)

    for name, prompt in PROMPTS.items():
        print(f"\n--- {name} ---")
        print(run_prompt(prompt, report))
    print()


if __name__ == "__main__":
    for number in range(1, len(REPORTS) + 1):
        compare(number)
