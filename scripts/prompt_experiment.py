"""
PROMPT EXPERIMENT (README section 19, exam Q3)

Runs SYSTEM_PROMPT, PROMPT_A, PROMPT_B and PROMPT_C on the same dev cases
and compares each answer with the answer key (data/labels.json).

Pipeline:
    Dev cases
        |
        v
    assess_case() with each prompt
        |
        v
    Compare with labels.json
        |
        v
    results.csv (one row per case and prompt) + summary.csv (one row per prompt)

Only indicators that can be found in the text are expected: indicators the
answer key found from the closed answers alone are left out, because the
model never sees those answers. Recorded calls are left out (they need Whisper).

Run from the project folder:
    python -m scripts.prompt_experiment              # 50 cases
    python -m scripts.prompt_experiment --cases 10   # quick check
    python -m scripts.prompt_experiment --prompts SYSTEM_PROMPT --append   # add one prompt to the results
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd

from app.llm.prompts import (PROMPT_A, PROMPT_B, PROMPT_C, SYSTEM_PROMPT, SYSTEM_PROMPT_V1,
                             SYSTEM_PROMPT_V2)
from app.services.assessment import assess_case, present_indicators
from app.services.rules import other_answer_for_model, read_answers


# 1. CONFIGURATION
DATA = Path("data")
OUTPUT_DIR = Path("evaluation/prompt_experiment")
PROMPTS = {"SYSTEM_PROMPT_V1": SYSTEM_PROMPT_V1, "SYSTEM_PROMPT_V2": SYSTEM_PROMPT_V2,
           "SYSTEM_PROMPT": SYSTEM_PROMPT,
           "PROMPT_A": PROMPT_A, "PROMPT_B": PROMPT_B, "PROMPT_C": PROMPT_C}
TEXT_SOURCES = {"report", "both", "answers_other_text"}   # evidence the model can see
SEED = 42


# 2. CHOOSE THE DEV CASES
def choose_cases(n_cases: int) -> list[dict]:
    """A fixed mix of field reports, helpline reports and "Other" answers from the dev split."""
    labels = json.loads((DATA / "labels.json").read_text())
    field = json.loads((DATA / "field_submissions.json").read_text())
    helpline = json.loads((DATA / "helpline_reports.json").read_text())

    field_cases, other_cases, helpline_cases = [], [], []
    for submission in field:
        label = labels[submission["case_uuid"]]
        if label["split"] != "dev" or label["status"] != "assessed":
            continue
        answers = read_answers(submission)
        case = {"case_id": label["id"], "channel": "field",
                "report": answers.get("closing_report", ""),
                "other_answer": other_answer_for_model(answers), "label": label}
        (other_cases if case["other_answer"] else field_cases).append(case)

    for call in helpline:
        label = labels[call["report_id"]]
        if label["split"] == "dev" and label["status"] == "assessed" and not call["recording_file"]:
            helpline_cases.append({"case_id": call["report_id"], "channel": "helpline",
                                   "report": call["report_text"], "other_answer": None, "label": label})

    rng = random.Random(SEED)
    n_other = min(len(other_cases), max(1, n_cases // 10))
    n_helpline = n_cases * 3 // 10
    n_field = n_cases - n_other - n_helpline
    return (rng.sample(field_cases, n_field) + rng.sample(helpline_cases, n_helpline)
            + rng.sample(other_cases, n_other))


# 3. COMPARE ONE ANSWER WITH THE ANSWER KEY
def compare(case: dict, result: dict) -> dict:
    """Counts for one case: correct, false alarms, missed, subtype errors."""
    expected = {i["id"]: i["subtype"] for i in case["label"]["indicators"] if i["source"] in TEXT_SOURCES}
    if not result["success"]:
        return {"expected": sorted(expected), "found": None, "correct": 0, "false_alarms": 0,
                "missed": len(expected), "subtype_errors": 0, "exact_match": False}

    found = {i["id"]: i["subtype"] for i in present_indicators(result["data"])}
    correct = expected.keys() & found.keys()
    return {
        "expected": sorted(expected),
        "found": sorted(found),
        "correct": len(correct),
        "false_alarms": len(found.keys() - expected.keys()),
        "missed": len(expected.keys() - found.keys()),
        "subtype_errors": sum(expected[i] != found[i] for i in correct),
        "exact_match": expected == found,
    }


# 4. RUN EVERY PROMPT ON EVERY CASE
def run(n_cases: int, prompt_names: list[str]) -> pd.DataFrame:
    cases = choose_cases(n_cases)
    rows = []
    for prompt_name in prompt_names:
        prompt = PROMPTS[prompt_name]
        print(f"\n{prompt_name}")
        for number, case in enumerate(cases, start=1):
            result = assess_case(case["case_id"], case["report"], case["other_answer"], system_prompt=prompt)
            data = result["data"]
            rows.append({
                "prompt": prompt_name,
                "case_id": case["case_id"],
                "channel": case["channel"],
                "success": result["success"],
                "attempts": result["attempts"],
                "error": result["error"],
                "latency_s": result["latency_s"],
                **compare(case, result),
                "summary_words": len(data.summary.split()) if data else None,
                "answer": json.dumps(data.model_dump()) if data else json.dumps(result["details"], default=str),
            })
            status = "ok" if result["success"] else f"FAILED ({result['error']})"
            print(f"  {number}/{len(cases)} {case['case_id'][:13]} {status}")
    return pd.DataFrame(rows)


# 5. SUMMARY: ONE ROW PER PROMPT
def summarise(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for prompt_name, group in results.groupby("prompt", sort=False):
        correct, false_alarms, missed = group["correct"].sum(), group["false_alarms"].sum(), group["missed"].sum()
        precision = correct / (correct + false_alarms) if correct + false_alarms else 0.0
        recall = correct / (correct + missed) if correct + missed else 0.0
        rows.append({
            "prompt": prompt_name,
            "cases": len(group),
            "exact_match_%": round(100 * group["exact_match"].mean(), 1),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "false_alarms": int(false_alarms),
            "missed": int(missed),
            "subtype_errors": int(group["subtype_errors"].sum()),
            "valid_first_try_%": round(100 * ((group["attempts"] == 1) & group["success"]).mean(), 1),
            "could_not_assess": int((~group["success"]).sum()),
            "avg_seconds": round(group["latency_s"].mean(), 1),
            "avg_summary_words": round(group["summary_words"].mean(), 1),
        })
    return pd.DataFrame(rows)


# 6. MAIN PROGRAM
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare the assessor prompts on dev cases")
    parser.add_argument("--cases", type=int, default=50)
    parser.add_argument("--prompts", nargs="+", choices=list(PROMPTS), default=list(PROMPTS))
    parser.add_argument("--append", action="store_true",
                        help="keep the other prompts already in results.csv")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = run(args.cases, args.prompts)
    if args.append and (OUTPUT_DIR / "results.csv").exists():
        old = pd.read_csv(OUTPUT_DIR / "results.csv")
        results = pd.concat([old[~old["prompt"].isin(args.prompts)], results], ignore_index=True)
    summary = summarise(results)

    results.to_csv(OUTPUT_DIR / "results.csv", index=False)
    summary.to_csv(OUTPUT_DIR / "summary.csv", index=False)

    print("\n" + "=" * 70)
    print("PROMPT EXPERIMENT SUMMARY")
    print("=" * 70)
    print(summary.to_string(index=False))
    print(f"\nSaved {OUTPUT_DIR / 'results.csv'} and {OUTPUT_DIR / 'summary.csv'}")
