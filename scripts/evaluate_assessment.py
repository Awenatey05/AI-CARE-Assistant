"""
EVALUATE THE ASSESSMENT

Compares every saved case with its answer in data/labels.json and measures how
well the whole assessment (Python rules, model, quote check, scoring) did:
indicators found, missed and wrongly flagged; the band; alerts missed and
raised by mistake; and how often a case could not be assessed. Results are
given for each group of the answer key: eval (never used to improve the
prompt), dev, helpline, edge cases and uploads.

    data/labels.json + cases in Postgres -> evaluation/assessment/
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from app.core.db import connect

LABELS = Path("data/labels.json")
OUTPUT = Path("evaluation/assessment")


def group(label: dict) -> str:
    return "helpline" if label["channel"] == "helpline" else label["split"]


def present(indicators: list[dict]) -> set[int]:
    return {i["id"] if "id" in i else i["indicator"] for i in indicators}


def answers(labels: dict, connection) -> list[tuple[str, dict]]:
    """(case id, answer) pairs. An upload's answer lists its children: a document or video has
    one child, saved under the upload's id; a sheet has many, each saved as a case of its own,
    found by the sheet's id and the child's name."""
    pairs = []
    for key, label in labels.items():
        if "children" not in label:
            pairs.append((key, label))
            continue
        for child in label["children"]:
            child = {**child, "channel": "upload", "split": label["split"]}
            if len(label["children"]) == 1:
                pairs.append((key, child))
                continue
            row = connection.execute("SELECT id FROM cases WHERE source_id = %s AND child_name = %s",
                                     (key, child["name"])).fetchone()
            if row:
                pairs.append((row["id"], child))
    return pairs


def main() -> None:
    labels = json.loads(LABELS.read_text())
    with connect() as connection:
        pairs = answers(labels, connection)
        cases = {c["id"]: c for c in connection.execute(
            "SELECT id, case_ref, channel, status, band, alert FROM cases WHERE id = ANY(%s)",
            ([case_id for case_id, _ in pairs],))}
        found = defaultdict(set)
        for row in connection.execute("SELECT case_id, indicator FROM indicators WHERE NOT observed "
                                      "AND case_id = ANY(%s)", (list(cases),)):
            found[row["case_id"]].add(row["indicator"])

    totals = defaultdict(Counter)                      # per group: cases, bands right, alerts, ...
    per_indicator = defaultdict(Counter)               # per indicator: found, missed, wrongly flagged
    rows = []
    for case_id, label in pairs:
        case = cases.get(case_id)
        if case is None:
            continue
        g, t = group(label), totals[group(label)]
        t["cases"] += 1
        t["could not assess"] += case["status"] == "could_not_assess"
        expected, got = present(label["indicators"]), found[case_id]
        if case["status"] != "could_not_assess":
            for i in range(1, 11):
                per_indicator[i]["found" if i in expected and i in got else
                                 "missed" if i in expected else
                                 "wrongly flagged" if i in got else "correctly absent"] += 1
            if label.get("band"):
                t["band given"] += 1
                t["band right"] += case["band"] == label["band"]
        t["alert expected"] += bool(label["alert"])
        t["alert missed"] += bool(label["alert"]) and not case["alert"]
        t["alert by mistake"] += bool(case["alert"]) and not label["alert"]
        rows.append({"case": case["case_ref"], "group": g, "status": case["status"],
                     "band expected": label.get("band"), "band": case["band"],
                     "alert expected": label["alert"], "alert": case["alert"],
                     "missed": sorted(expected - got), "wrongly flagged": sorted(got - expected)})

    OUTPUT.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT / "per_case.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    lines = ["ASSESSMENT COMPARED WITH THE ANSWER KEY (data/labels.json)", ""]
    lines.append(f"{'group':10} {'cases':>6} {'band right':>11} {'alerts missed':>14} {'alerts by mistake':>18} "
                 f"{'could not assess':>17}")
    for g in ("eval", "dev", "helpline", "edge", "upload"):
        t = totals[g]
        if t["cases"]:
            band = f"{100 * t['band right'] / t['band given']:.0f}%" if t["band given"] else "-"
            lines.append(f"{g:10} {t['cases']:>6} {band:>11} {t['alert missed']:>5} of {t['alert expected']:<6} "
                         f"{t['alert by mistake']:>18} {100 * t['could not assess'] / t['cases']:>16.0f}%")
    lines += ["", "INDICATORS (all groups; cases that could not be assessed left out)",
              f"{'indicator':10} {'found':>6} {'missed':>7} {'wrongly flagged':>16} {'recall':>7} {'precision':>10}"]
    for i in range(1, 11):
        n = per_indicator[i]
        recall = n["found"] / (n["found"] + n["missed"]) if n["found"] + n["missed"] else 0
        precision = n["found"] / (n["found"] + n["wrongly flagged"]) if n["found"] + n["wrongly flagged"] else 0
        lines.append(f"{i:<10} {n['found']:>6} {n['missed']:>7} {n['wrongly flagged']:>16} {recall:>7.0%} {precision:>10.0%}")
    (OUTPUT / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
