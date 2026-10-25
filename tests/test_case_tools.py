"""The case tools in the real Postgres database. The tools share the test's connection,
so everything is rolled back at the end and nothing is left behind.
Skipped if Postgres is not running."""

from __future__ import annotations

import psycopg
import pytest
from pydantic import ValidationError

from app.core.db import connect, create_tables
from app.services.case_store import save_case
from app.tools import case_tools
from app.tools.case_tools import make_case_tools

CASES = [
    {"id": "test-tool-1", "region": "test_north", "district": "Tamale", "community": "Gumani", "band": "High",
     "score": 4, "urgent_reasons": ["critical_indicator:1"], "masked_text": "[NAME] was beaten. Call [PHONE].",
     "original_key": "field/test-tool-1.json",
     "indicators": [{"id": 1, "source": "report", "quote": "[NAME] was beaten."},
                    {"id": 7, "source": "answers", "quote": None}]},
    {"id": "test-tool-2", "region": "test_north", "district": "Tamale", "community": "Gumani", "band": "Low",
     "score": 1, "masked_text": "He misses school most weeks.",
     "indicators": [{"id": 7, "source": "report", "quote": "He misses school most weeks."}]},
    {"id": "test-tool-3", "region": "test_north", "district": "Savelugu", "community": "Diare", "band": "High",
     "score": 6, "masked_text": "x", "indicators": []},
    {"id": "test-tool-4", "region": "test_south", "district": "Krachi East", "community": "Dambai", "band": "High",
     "score": 5, "masked_text": "x", "indicators": []},
]


class Shared:
    """The test's connection, lent to the tools: 'with' and close() leave it open."""
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        return self

    def __exit__(self, *error):
        return False

    def close(self):
        pass


@pytest.fixture
def tools(monkeypatch):
    try:
        create_tables()
        connection = connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running (docker compose up -d)")
    refs = {case["id"]: save_case({"channel": "field", "status": "assessed", "child_name": "Ama Mensah",
                                   "alert": False, **case}, connection=connection) for case in CASES}
    monkeypatch.setattr(case_tools, "connect", lambda: Shared(connection))
    monkeypatch.setattr(case_tools.storage, "read_json", lambda key: {"_attachments": [
        {"question_xpath": "safety/injury_photo"}, {"question_xpath": "worker/living_conditions_photo"}]})
    yield {t.name: t for t in make_case_tools("test_north")}, refs
    connection.rollback()
    connection.close()


def test_count_by_band_inside_the_region_only(tools):
    t, _ = tools
    result = t["count_cases"].invoke({"band": "High"})
    assert (result["region"], result["total"], result["by_band"]) == ("test_north", 2, {"High": 2})


def test_place_matches_a_community_or_a_district_ignoring_capitals(tools):
    t, _ = tools
    assert t["count_cases"].invoke({"place": "gumani"})["total"] == 2
    assert t["count_cases"].invoke({"place": "Savelugu", "band": "High"})["total"] == 1
    assert t["count_cases"].invoke({"place": "Tam"})["total"] == 2          # the start of "Tamale"


def test_a_region_from_the_model_is_ignored(tools):
    t, _ = tools
    assert t["count_cases"].invoke({"band": "High", "region": "test_south"})["total"] == 2   # still test_north


def test_list_by_indicator_most_serious_first_with_quotes(tools):
    t, _ = tools
    result = t["list_cases"].invoke({"indicator": 7, "place": "Gumani"})
    assert [c["band"] for c in result["cases"]] == ["High", "Low"]
    assert result["cases"][1]["quote"] == "He misses school most weeks."


def test_show_case_gives_the_reasons_but_no_personal_details(tools):
    t, refs = tools
    case = t["show_case"].invoke({"case_ref": refs["test-tool-1"].lower()})
    assert case["found"] and case["urgent_reasons"] == ["critical_indicator:1"]
    assert [(i["indicator"], i["name"]) for i in case["indicators"]] == [(1, "Physical violence or injury"),
                                                                          (7, "Out of school")]
    assert case["phone_number_in_report"] is True
    assert case["attachments"] == ["injury photo", "living conditions photo"]
    assert "Ama" not in str(case)


def test_a_case_in_another_region_is_not_found(tools):
    t, refs = tools
    assert t["show_case"].invoke({"case_ref": refs["test-tool-4"]})["found"] is False


def test_wrong_arguments_are_refused(tools):
    t, _ = tools
    with pytest.raises(ValidationError):
        t["count_cases"].invoke({"band": "Very high"})
    with pytest.raises(ValidationError):
        t["list_cases"].invoke({"indicator": 11})


def test_finding_by_name_needs_the_ok_first(tools):
    t, _ = tools
    with pytest.raises(PermissionError):
        t["find_case_by_name"].invoke({"name": "Ama"})


def test_finding_by_name_gives_references_in_the_region_only(tools):
    t, refs = tools
    result = t["find_case_by_name"].invoke({"name": "ama MENSAH"}, approved=True)
    assert sorted(c["case_ref"] for c in result["cases"]) == sorted(refs[i] for i in ("test-tool-1", "test-tool-2",
                                                                                     "test-tool-3"))
    assert "Ama" not in str(result["cases"])
    assert t["find_case_by_name"].invoke({"name": "Kofi"}, approved=True)["found"] == 0
