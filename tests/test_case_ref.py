"""Readable case references (NR-TML-GUM-0012-2026), in the real database, rolled back after each test."""

from __future__ import annotations

import psycopg
import pytest

from app.core.db import connect, create_tables
from app.services.case_ref import case_reference, community_code, district_code, place_code
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


@pytest.mark.parametrize("name,code", [("Tamale Metropolitan", "TML"), ("Nkwanta North", "NKWN"),
                                       ("Nkwanta South", "NKWS"), ("East Gonja", "GNJE"),
                                       ("Wa Municipal", "WA"), ("Savelugu", "SVL")])
def test_district_codes(name, code):
    assert district_code(name) == code


def test_community_code():
    assert community_code("Gumani") == "GUM"


def test_reference_from_the_list(db):
    first = case_reference(db, "northern", "Tamale Metropolitan", "Gumani", "2026-03-01")
    second = case_reference(db, "northern", "Tamale Metropolitan", "Gumani", "2026-05-01")
    assert first.startswith("NR-TML-GUM-") and first.endswith("-2026")
    assert int(second.split("-")[3]) == int(first.split("-")[3]) + 1      # next number


def test_numbers_start_again_each_year(db):
    a = case_reference(db, "oti", "Krachi East", "Dambai", "2031-01-01")
    b = case_reference(db, "oti", "Krachi East", "Dambai", "2032-01-01")
    assert a == "OT-KRCE-DAM-0001-2031" and b == "OT-KRCE-DAM-0001-2032"


def test_new_place_is_coded_by_the_rule_and_marked_unchecked(db):
    assert place_code(db, "community", "Gumbiya", "Tamale Metropolitan") == "GUM2"   # GUM is taken there
    row = db.execute("SELECT checked FROM place_codes WHERE name = 'Gumbiya'").fetchone()
    assert row["checked"] is False
    assert place_code(db, "community", "Gumbiya", "Tamale Metropolitan") == "GUM2"   # same code next time


def test_all_sixteen_regions_listed(db):
    assert db.execute("SELECT count(*) FROM place_codes WHERE kind = 'region'").fetchone()["count"] == 16


def test_reference_kept_when_the_case_is_saved_again(db):
    case = {"id": "ref-test-1", "channel": "helpline", "region": "northern", "district": "Savelugu",
            "status": "assessed", "score": 0, "band": "No risk", "received_at": "2026-02-01"}
    save_case(case, connection=db)
    ref = get_case("ref-test-1", connection=db)["case_ref"]
    save_case({**case, "score": 1, "band": "Low"}, connection=db)
    assert get_case("ref-test-1", connection=db)["case_ref"] == ref and ref.startswith("NR-SVL-")
