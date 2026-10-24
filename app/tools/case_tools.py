"""The case tools: counting, listing and showing cases (Postgres).

The verdicts were made once, at intake (rules, model, quote check, scoring),
and are read here from the database; nothing is judged again and no number
is guessed by the model.

    count_cases  "How many High cases are there in Savelugu?"
    list_cases   "Which children in Gumani are out of school?"
    show_case    "Why is NR-TML-GUM-0012-2026 High? What was the report?"

The tools are made for one region (the user's), when the chat starts. The
region is not an argument the model can set, so a team leader never gets an
answer about another region; a case elsewhere is simply "not found".

Personal details never pass through the model: show_case says whether the
report contains a phone number and which photos, recordings or videos the
case has, but not the number or the files. The officer opens those in the
dashboard.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.db import connect
from app.services import storage
from app.tools.agents import Tool

# 1. NAMES AND CHOICES
INDICATOR_NAMES = {1: "Physical violence or injury", 2: "Sexual abuse or exploitation", 3: "Neglect",
                   4: "Child labour", 5: "Child marriage and harmful practices", 6: "Trafficking, separated child",
                   7: "Out of school", 8: "Unsafe or absent caregiver", 9: "Emotional distress",
                   10: "No legal identity, discrimination"}
Band = Literal["No risk", "Low", "Moderate", "High"]
Channel = Literal["field", "helpline", "upload"]
Status = Literal["assessed", "human_review", "could_not_assess", "not_scored_incomplete", "not_scored_no_consent",
                 "needs_transcription"]
BAND_ORDER = "CASE band WHEN 'High' THEN 4 WHEN 'Moderate' THEN 3 WHEN 'Low' THEN 2 WHEN 'No risk' THEN 1 ELSE 0 END"
PHOTOS = {"safety/injury_photo": "injury photo", "worker/living_conditions_photo": "living conditions photo"}
VIDEO = {".mp4", ".mov"}


class CaseFilters(BaseModel):
    band: Band | None = None
    indicator: int | None = Field(default=None, ge=1, le=10, description="indicator number 1-10")
    district: str | None = None
    community: str | None = None
    channel: Channel | None = None
    status: Status | None = None


class ListArgs(CaseFilters):
    limit: int = Field(default=10, ge=1, le=25)


class ShowArgs(BaseModel):
    case_ref: str = Field(min_length=5, description="a case reference such as NR-TML-GUM-0012-2026")


# 2. FILTERS (always inside the user's region)
def where(region: str | None, filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    parts, params = ["TRUE"], {}
    if region:
        parts.append("c.region = %(region)s")
        params["region"] = region
    for column in ("band", "channel", "status"):
        if filters.get(column):
            parts.append(f"c.{column} = %({column})s")
            params[column] = filters[column]
    for column in ("district", "community"):
        if filters.get(column):
            parts.append(f"lower(c.{column}) = lower(%({column})s)")
            params[column] = filters[column].strip()
    if filters.get("indicator"):
        parts.append("EXISTS (SELECT 1 FROM indicators i WHERE i.case_id = c.id AND i.indicator = %(indicator)s "
                     "AND NOT i.observed)")
        params["indicator"] = filters["indicator"]
    return " AND ".join(parts), params


# 3. THE TOOLS
def count_cases(region: str | None, **filters: Any) -> dict[str, Any]:
    sql, params = where(region, filters)
    rows = connect().execute(f"SELECT coalesce(c.band, 'no band') AS band, count(*) AS n FROM cases c WHERE {sql} "
                             "GROUP BY 1", params).fetchall()
    by_band = {row["band"]: row["n"] for row in rows}
    return {"region": region or "all regions", "filters": {k: v for k, v in filters.items() if v},
            "total": sum(by_band.values()), "by_band": by_band}


def list_cases(region: str | None, limit: int = 10, **filters: Any) -> dict[str, Any]:
    sql, params = where(region, filters)
    with connect() as connection:
        total = connection.execute(f"SELECT count(*) AS n FROM cases c WHERE {sql}", params).fetchone()["n"]
        rows = connection.execute(
            f"SELECT c.id, c.case_ref, c.band, c.score, c.status, c.district, c.community, c.channel, "
            f"c.urgent_reasons FROM cases c WHERE {sql} ORDER BY {BAND_ORDER} DESC, c.score DESC NULLS LAST, "
            "c.received_at DESC LIMIT %(limit)s", {**params, "limit": limit}).fetchall()
        quotes = {}
        if filters.get("indicator"):
            for row in connection.execute(
                    "SELECT case_id, quote FROM indicators WHERE indicator = %s AND case_id = ANY(%s) AND NOT observed",
                    (filters["indicator"], [r["id"] for r in rows])):
                quotes[row["case_id"]] = row["quote"]
    cases = [{"case_ref": r["case_ref"], "band": r["band"], "score": r["score"], "status": r["status"],
              "district": r["district"], "community": r["community"], "channel": r["channel"],
              "urgent_reasons": r["urgent_reasons"], **({"quote": quotes.get(r["id"])} if quotes else {})}
             for r in rows]
    return {"region": region or "all regions", "total_matching": total, "shown": len(cases), "cases": cases}


def attachments(channel: str, original_key: str | None) -> list[str]:
    """Which photos, recordings or videos the case has: their kind only, never the files."""
    if not original_key:
        return []
    try:
        if channel == "field":
            found = storage.read_json(original_key).get("_attachments") or []
            return [PHOTOS.get(a.get("question_xpath"), "photo") for a in found]
        if channel == "helpline":
            return ["call recording"] if storage.read_json(original_key).get("recording_file") else []
    except Exception:
        return ["(could not be checked now)"]
    return ["video statement"] if any(original_key.lower().endswith(s) for s in VIDEO) else []


def show_case(region: str | None, case_ref: str) -> dict[str, Any]:
    with connect() as connection:
        case = connection.execute("SELECT * FROM cases WHERE case_ref = %s", (case_ref.strip().upper(),)).fetchone()
        if case is None or (region and case["region"] != region):
            return {"found": False, "case_ref": case_ref, "message": "No case with this reference in your region."}
        indicators = connection.execute(
            "SELECT indicator, subtype, source, quote, observed FROM indicators WHERE case_id = %s ORDER BY indicator",
            (case["id"],)).fetchall()
        alerts = connection.execute("SELECT priority, status, escalation_level FROM alerts WHERE case_id = %s "
                                    "ORDER BY created_at", (case["id"],)).fetchall()
    text = case["masked_text"] or ""
    return {
        "found": True, "case_ref": case["case_ref"], "channel": case["channel"], "district": case["district"],
        "community": case["community"], "received_at": str(case["received_at"] or ""),
        "status": case["status"], "band": case["band"], "score": case["score"],
        "urgent_reasons": case["urgent_reasons"], "flags": case["flags"], "summary": case["summary"],
        "indicators": [{"indicator": i["indicator"], "name": INDICATOR_NAMES[i["indicator"]], "subtype": i["subtype"],
                        "found_in": i["source"], "quote": i["quote"],
                        "confirmed": not i["observed"]} for i in indicators],
        "alerts": [dict(a) for a in alerts],
        "report_masked": text,
        "phone_number_in_report": "[PHONE]" in text,
        "attachments": attachments(case["channel"], case["original_key"]),
    }


# 4. THE TOOLS FOR ONE REGION
def make_case_tools(region: str | None) -> list[Tool]:
    """The case tools for one user's region (None only for the super administrator)."""
    return [
        Tool("count_cases", "Count cases, optionally by band, indicator (1-10), district, community, channel or "
             "status. Use it for every 'how many' question.", CaseFilters,
             lambda **f: count_cases(region, **f)),
        Tool("list_cases", "List cases (references, band, score, place), most serious first, with the same filters "
             "as count_cases. With an indicator, each case's supporting quote is included.", ListArgs,
             lambda **f: list_cases(region, **f)),
        Tool("show_case", "Show one case by its reference: band, score, urgent reasons, each indicator with its "
             "quote, the masked report, alerts, whether the report has a phone number, and which photos, "
             "recordings or videos it has.", ShowArgs,
             lambda case_ref: show_case(region, case_ref)),
    ]
