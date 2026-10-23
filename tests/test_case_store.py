"""Saving and reading cases in the real Postgres database.

Every test runs inside a transaction that is rolled back at the end,
so the tests never leave data behind. They are skipped if Postgres is not running.
"""

from __future__ import annotations

import psycopg
import pytest

from app.core.db import connect, create_tables
from app.services.case_store import get_case, save_case


@pytest.fixture
def db():
    try:
        create_tables()
        connection = connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running (docker compose up -d)")
    yield connection
    connection.rollback()
    connection.close()


def a_case(**changes):
    case = {"id": "test-case-1", "channel": "field", "region": "northern", "status": "assessed",
            "score": 2, "band": "High", "alert": True, "urgent_reasons": ["critical_indicator:1"],
            "flags": ["local_language"], "child_name": "Test Child",
            "indicators": [{"id": 1, "subtype": None, "source": "both", "quote": "He was hit."},
                           {"id": 7, "subtype": None, "source": "answers"}]}
    case.update(changes)
    return case


def test_save_and_read_back(db):
    save_case(a_case(), connection=db)
    case = get_case("test-case-1", connection=db)
    assert (case["band"], case["score"], case["alert"]) == ("High", 2, True)
    assert case["urgent_reasons"] == ["critical_indicator:1"]
    assert [i["indicator"] for i in case["indicators"]] == [1, 7]
    assert case["indicators"][0]["quote"] == "He was hit."


def test_alert_opened_once(db):
    save_case(a_case(), connection=db)
    save_case(a_case(), connection=db)                 # the same job runs twice
    alerts = get_case("test-case-1", connection=db)["alerts"]
    assert len(alerts) == 1 and alerts[0]["status"] == "open"


def test_saving_again_replaces_the_case(db):
    save_case(a_case(), connection=db)
    save_case(a_case(score=0, band="No risk", alert=False, urgent_reasons=[], indicators=[]), connection=db)
    case = get_case("test-case-1", connection=db)
    assert (case["band"], case["indicators"]) == ("No risk", [])


def test_no_alert_for_a_case_without_urgent_flags(db):
    save_case(a_case(alert=False, urgent_reasons=[]), connection=db)
    assert get_case("test-case-1", connection=db)["alerts"] == []


def test_urgent_alert_has_urgent_priority(db):
    save_case(a_case(), connection=db)
    assert get_case("test-case-1", connection=db)["alerts"][0]["priority"] == "urgent"


def test_could_not_assess_gets_a_review_notice_once(db):
    failed = a_case(status="could_not_assess", score=None, band=None, alert=False, urgent_reasons=[])
    save_case(failed, connection=db)
    save_case(failed, connection=db)
    alerts = get_case("test-case-1", connection=db)["alerts"]
    assert [(a["priority"], a["reasons"]) for a in alerts] == [("review", ["could_not_assess"])]


def test_could_not_assess_with_urgent_rules_gets_the_urgent_alert(db):
    save_case(a_case(status="could_not_assess", score=None, band=None), connection=db)
    assert [a["priority"] for a in get_case("test-case-1", connection=db)["alerts"]] == ["urgent"]


def test_observed_indicators_kept_but_marked(db):
    save_case(a_case(status="human_review", score=None, band=None, indicators=[],
                     observed_indicators=[{"id": 1, "subtype": None, "source": "report", "quote": "x"}]),
              connection=db)
    found = get_case("test-case-1", connection=db)["indicators"]
    assert found[0]["observed"] is True


def test_unknown_case(db):
    assert get_case("no-such-case", connection=db) is None


def test_invalid_band_rejected_by_the_database(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        save_case(a_case(band="Very high"), connection=db)
