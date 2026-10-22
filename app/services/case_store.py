"""Saving and reading case records (Postgres).

The pipeline hands over one finished case as a dictionary; this module
writes it to the cases, indicators and alerts tables. Saving the same
case again replaces it (for example after a re-assessment), so a job
that runs twice does not create duplicates.
"""

from __future__ import annotations

from typing import Any

import psycopg

from app.core.db import connect

CASE_COLUMNS = ["id", "channel", "source_id", "region", "district", "community", "child_name",
                "status", "score", "band", "alert", "urgent_reasons", "flags", "summary",
                "masked_text", "original_key", "received_at"]


# 1. SAVE
def save_case(case: dict[str, Any], connection: psycopg.Connection | None = None) -> None:
    """Insert or replace one case, its indicators, and open an alert if needed."""
    own = connection is None
    connection = connection or connect()
    try:
        values = {column: case.get(column) for column in CASE_COLUMNS}
        values["urgent_reasons"] = values["urgent_reasons"] or []
        values["flags"] = values["flags"] or []
        values["alert"] = bool(values["alert"])
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in CASE_COLUMNS if c != "id")
        connection.execute(
            f"INSERT INTO cases ({', '.join(CASE_COLUMNS)}) "
            f"VALUES ({', '.join('%(' + c + ')s' for c in CASE_COLUMNS)}) "
            f"ON CONFLICT (id) DO UPDATE SET {updates}",
            values,
        )

        # Indicators: replace them all, so a re-assessment never leaves old findings behind.
        connection.execute("DELETE FROM indicators WHERE case_id = %s", (case["id"],))
        for observed, key in ((False, "indicators"), (True, "observed_indicators")):
            for found in case.get(key) or []:
                connection.execute(
                    "INSERT INTO indicators (case_id, indicator, subtype, source, quote, observed) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (case["id"], found["id"], found.get("subtype"), found["source"], found.get("quote"), observed),
                )

        # Alert: one open alert per case at most.
        if values["alert"]:
            open_alert = connection.execute(
                "SELECT id FROM alerts WHERE case_id = %s AND status = 'open'", (case["id"],)).fetchone()
            if not open_alert:
                connection.execute("INSERT INTO alerts (case_id, reasons) VALUES (%s, %s)",
                                   (case["id"], values["urgent_reasons"]))
        if own:
            connection.commit()
    finally:
        if own:
            connection.close()


# 2. READ
def get_case(case_id: str, connection: psycopg.Connection | None = None) -> dict[str, Any] | None:
    """One case with its indicators and alerts, or None if it does not exist."""
    own = connection is None
    connection = connection or connect()
    try:
        case = connection.execute("SELECT * FROM cases WHERE id = %s", (case_id,)).fetchone()
        if case is None:
            return None
        case["indicators"] = connection.execute(
            "SELECT indicator, subtype, source, quote, observed FROM indicators "
            "WHERE case_id = %s ORDER BY indicator", (case_id,)).fetchall()
        case["alerts"] = connection.execute(
            "SELECT id, reasons, status, escalation_level, created_at FROM alerts "
            "WHERE case_id = %s ORDER BY created_at", (case_id,)).fetchall()
        return case
    finally:
        if own:
            connection.close()
