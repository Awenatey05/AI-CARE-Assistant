"""The notifier, in the real Postgres database (rolled back after each test).

Skipped if Postgres is not running.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import psycopg
import pytest

from app.core.db import connect, create_tables
from app.services import notifier
from app.services.case_store import get_case, save_case


@pytest.fixture
def db():
    try:
        create_tables()
        connection = connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running (docker compose up -d)")
    # Set real alerts aside so only this test's alerts count; the rollback restores them.
    connection.execute("UPDATE alerts SET status = 'confirmed' WHERE status = 'open'")
    yield connection
    connection.rollback()
    connection.close()


def an_urgent_case(case_id="test-notify-1", **changes):
    case = {"id": case_id, "channel": "field", "region": "northern", "district": "Tamale",
            "community": "Gumani", "status": "assessed", "score": 7, "band": "High", "alert": True,
            "urgent_reasons": ["critical_indicator:1"], "child_name": "Test Child", "indicators": []}
    case.update(changes)
    return case


def the_alert(db, case_id="test-notify-1"):
    return get_case(case_id, connection=db)["alerts"][0]


def test_new_alert_sent_once_to_the_region_without_names(db, caplog):
    save_case(an_urgent_case(), connection=db)
    with caplog.at_level(logging.INFO, logger="notifier"):
        assert notifier.notify_new(connection=db) == 1
        assert notifier.notify_new(connection=db) == 0            # not sent twice
    message = caplog.messages[0]
    assert "team leader, regional supervisor" in message and "national lead" not in message
    assert "critical_indicator:1" in message and "Test Child" not in message


def test_unconfirmed_urgent_alert_escalates_to_the_lead(db, caplog):
    save_case(an_urgent_case(), connection=db)
    notifier.notify_new(connection=db)
    created = the_alert(db)["created_at"]
    hours = notifier.ALERT_ESCALATE_HOURS
    assert notifier.escalate_due(now=created + timedelta(hours=hours * 0.5), connection=db) == 0
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="notifier"):
        assert notifier.escalate_due(now=created + timedelta(hours=hours * 1.1), connection=db) == 1
        assert notifier.escalate_due(now=created + timedelta(hours=hours * 1.2), connection=db) == 0
        assert notifier.escalate_due(now=created + timedelta(hours=hours * 2.1), connection=db) == 1
    assert the_alert(db)["escalation_level"] == 2
    sent = [r.getMessage() for r in caplog.records if r.name == "notifier"]
    assert len(sent) == 2 and all("national lead" in m for m in sent)


def test_review_notice_sent_but_never_escalated(db):
    save_case(an_urgent_case(status="could_not_assess", score=None, band=None, alert=False, urgent_reasons=[]),
              connection=db)
    assert notifier.notify_new(connection=db) == 1
    created = the_alert(db)["created_at"]
    assert notifier.escalate_due(now=created + timedelta(days=30), connection=db) == 0


def test_confirmed_alert_stops_escalating(db):
    save_case(an_urgent_case(), connection=db)
    alert = the_alert(db)
    assert notifier.confirm(alert["id"], "Team Leader Test", connection=db) is True
    assert notifier.confirm(alert["id"], "Someone Else", connection=db) is False    # already confirmed
    assert notifier.escalate_due(now=alert["created_at"] + timedelta(days=30), connection=db) == 0
    assert the_alert(db)["status"] == "confirmed"


def test_open_alerts_urgent_first_and_by_region(db):
    save_case(an_urgent_case("test-notify-review", status="could_not_assess", score=None, band=None,
                             alert=False, urgent_reasons=[]), connection=db)
    save_case(an_urgent_case("test-notify-urgent"), connection=db)
    save_case(an_urgent_case("test-notify-oti", region="oti", district="Krachi East", community="Dambai"),
              connection=db)
    northern = [a for a in notifier.open_alerts("northern", connection=db) if a["case_ref"]]
    ours = [a["priority"] for a in northern if a["district"] == "Tamale" and a["band"] in ("High", None)]
    assert ours.index("urgent") < ours.index("review")
    assert all(a["region"] == "northern" for a in northern)
