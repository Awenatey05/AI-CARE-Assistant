"""The notifier: tells the right people about alerts, and escalates them.

The worker opens an alert when it saves an urgent case (case_store.py).
The notifier then:
    - sends each new alert to the team leader and regional supervisor;
    - escalates an urgent alert nobody has confirmed, adding the national lead,
      and reminds all three every ALERT_ESCALATE_HOURS until someone confirms;
    - closes an alert when a person confirms it in the dashboard.

Review notices ("could not assess" cases) are sent once and never escalate.

Sending is a log line for now; the dashboard shows the same alerts from the
database. Messages carry the case reference and reason codes only, never a
child's name or report text.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import psycopg

from app.core.db import connect
from config import ALERT_ESCALATE_HOURS

log = logging.getLogger("notifier")

# 1. WHO IS TOLD
REGION_ROLES = ["team leader", "regional supervisor"]
ESCALATION_ROLES = REGION_ROLES + ["national lead"]


def recipients(level: int) -> list[str]:
    """Level 0 goes to the region; from level 1 the national lead is added."""
    return ESCALATION_ROLES if level >= 1 else REGION_ROLES


def send(alert: dict[str, Any], level: int) -> None:
    """Deliver one alert. Today: a log line. Email or SMS would be added here."""
    kind = "REVIEW" if alert["priority"] == "review" else "ALERT"
    log.warning("%s %s (%s) level %d -> %s: %s", kind, alert["case_ref"], alert["region"], level,
                ", ".join(recipients(level)), ", ".join(alert["reasons"]))


def _open(connection: psycopg.Connection | None) -> tuple[psycopg.Connection, bool]:
    return (connection, False) if connection is not None else (connect(), True)


ALERT_WITH_CASE = (
    "SELECT a.id, a.reasons, a.priority, a.status, a.escalation_level, a.created_at, a.notified_at, "
    "c.case_ref, c.region, c.district, c.band FROM alerts a JOIN cases c ON c.id = a.case_id ")


# 2. NEW ALERTS
def notify_new(connection: psycopg.Connection | None = None) -> int:
    """Send every open alert that has not been sent yet. Returns how many were sent."""
    connection, own = _open(connection)
    try:
        new = connection.execute(ALERT_WITH_CASE + "WHERE a.status = 'open' AND a.notified_at IS NULL "
                                 "ORDER BY a.created_at").fetchall()
        for alert in new:
            send(alert, alert["escalation_level"])
            connection.execute("UPDATE alerts SET notified_at = now() WHERE id = %s", (alert["id"],))
        if own:
            connection.commit()
        return len(new)
    finally:
        if own:
            connection.close()


# 3. ESCALATION
def escalate_due(now: datetime | None = None, connection: psycopg.Connection | None = None) -> int:
    """Raise the level of urgent alerts left unconfirmed for another ALERT_ESCALATE_HOURS.
    Returns how many were escalated."""
    now = now or datetime.now(timezone.utc)
    connection, own = _open(connection)
    try:
        waiting = connection.execute(ALERT_WITH_CASE + "WHERE a.status = 'open' AND a.priority = 'urgent'").fetchall()
        escalated = 0
        for alert in waiting:
            hours_open = (now - alert["created_at"]).total_seconds() / 3600
            level = int(hours_open // ALERT_ESCALATE_HOURS)
            if level > alert["escalation_level"]:
                send(alert, level)
                connection.execute("UPDATE alerts SET escalation_level = %s, notified_at = %s WHERE id = %s",
                                   (level, now, alert["id"]))
                escalated += 1
        if own:
            connection.commit()
        return escalated
    finally:
        if own:
            connection.close()


def run_once(connection: psycopg.Connection | None = None) -> tuple[int, int]:
    """One round of the notifier: send new alerts, then escalate overdue ones."""
    return notify_new(connection), escalate_due(connection=connection)


# 4. CONFIRMATION (from the dashboard)
def confirm(alert_id: int, confirmed_by: str, connection: psycopg.Connection | None = None) -> bool:
    """Close an open alert. Returns False if it does not exist or was already confirmed."""
    connection, own = _open(connection)
    try:
        row = connection.execute(
            "UPDATE alerts SET status = 'confirmed', confirmed_by = %s, confirmed_at = now() "
            "WHERE id = %s AND status = 'open' RETURNING id", (confirmed_by.strip(), alert_id)).fetchone()
        if own:
            connection.commit()
        if row:
            log.info("alert %d confirmed", alert_id)
        return row is not None
    finally:
        if own:
            connection.close()


# 5. FOR THE DASHBOARD
def open_alerts(region: str | None = None, connection: psycopg.Connection | None = None) -> list[dict[str, Any]]:
    """Open alerts, urgent first, then the most escalated, then the oldest."""
    connection, own = _open(connection)
    try:
        where, params = "WHERE a.status = 'open' ", []
        if region:
            where += "AND c.region = %s "
            params.append(region)
        return connection.execute(
            ALERT_WITH_CASE + where + "ORDER BY a.priority = 'review', a.escalation_level DESC, a.created_at",
            params).fetchall()
    finally:
        if own:
            connection.close()
