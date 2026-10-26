"""The API (FastAPI TestClient): intake is replaced by a fake, so nothing is saved or queued."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from app.api import kobo

SECRET = "test-secret"


@pytest.fixture
def api(monkeypatch):
    queued = []
    monkeypatch.setattr(kobo, "KOBO_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(kobo.intake, "receive_field_submission", lambda s: queued.append(s) or "job-12345678")
    return TestClient(main.app), queued


def test_genuine_submission_is_queued(api):
    client, queued = api
    response = client.post("/kobo", json={"case_uuid": "abc-123"}, headers={"X-Webhook-Secret": SECRET})
    assert response.status_code == 202
    assert response.json() == {"status": "queued", "job_id": "job-12345678"}
    assert queued == [{"case_uuid": "abc-123"}]


@pytest.mark.parametrize("headers", [{}, {"X-Webhook-Secret": "wrong"}])
def test_submission_without_the_secret_is_refused(api, headers):
    client, queued = api
    assert client.post("/kobo", json={"case_uuid": "abc"}, headers=headers).status_code == 401
    assert queued == []


def test_submission_without_case_uuid_is_refused(api):
    client, queued = api
    response = client.post("/kobo", json={"child/age": "12"}, headers={"X-Webhook-Secret": SECRET})
    assert response.status_code == 422 and queued == []


def test_not_configured_refuses_everything(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(kobo, "KOBO_WEBHOOK_SECRET", None)
    assert client.post("/kobo", json={"case_uuid": "a"}, headers={"X-Webhook-Secret": ""}).status_code == 503


def test_storage_or_queue_down_gives_503(api, monkeypatch):
    client, _ = api
    def down(s):
        raise ConnectionError("Redis is not running")
    monkeypatch.setattr(kobo.intake, "receive_field_submission", down)
    response = client.post("/kobo", json={"case_uuid": "abc"}, headers={"X-Webhook-Secret": SECRET})
    assert response.status_code == 503      # Kobo retries a failed delivery later


def test_health_reports_each_part(monkeypatch):
    from app.api import health
    monkeypatch.setattr(health, "check_ollama", lambda: False)
    response = TestClient(main.app).get("/health")
    body = response.json()
    assert set(body) == {"status", "postgres", "redis", "storage", "ollama"}
    assert body["ollama"] is False and response.status_code == 503 and body["status"] == "degraded"


# ------------------------------------------------
# Office intake: helpline reports and uploads
# ------------------------------------------------

from app.api import office  # noqa: E402

KEY = {"X-Api-Key": "test-key"}


@pytest.fixture
def office_api(monkeypatch):
    received = []
    monkeypatch.setattr(office, "API_KEY", "test-key")
    monkeypatch.setattr(office.intake, "receive_helpline_call",
                        lambda call, path: received.append((call, path and path.name)) or "job-1")
    monkeypatch.setattr(office.intake, "receive_upload",
                        lambda entry, path: received.append((entry, path.name)) or "job-2")
    return TestClient(main.app), received


REPORT = {"region": "Northern", "district": "Savelugu", "report_text": "The child said there was no food at home."}


def test_typed_helpline_report_queued(office_api):
    client, received = office_api
    response = client.post("/helpline", data=REPORT, headers=KEY)
    assert response.status_code == 202 and response.json()["report_id"].startswith("HL-")
    call, recording = received[0]
    assert (call["region"], call["recording_file"], recording) == ("northern", None, None)


def test_recording_with_consent(office_api):
    client, received = office_api
    response = client.post("/helpline", data={**REPORT, "consent_to_record": "true"},
                           files={"recording": ("call.m4a", b"audio", "audio/mp4")}, headers=KEY)
    call, recording = received[0]
    assert response.status_code == 202 and recording == call["recording_file"] == f"{call['report_id']}.m4a"


def test_recording_without_consent_refused(office_api):
    client, received = office_api
    response = client.post("/helpline", data=REPORT, files={"recording": ("call.m4a", b"audio", "audio/mp4")},
                           headers=KEY)
    assert response.status_code == 422 and received == []


@pytest.mark.parametrize("change", [{"region": "Atlantis"}, {"report_text": "too short"}])
def test_invalid_report_refused(office_api, change):
    client, received = office_api
    assert client.post("/helpline", data={**REPORT, **change}, headers=KEY).status_code == 422
    assert received == []


def test_office_routes_need_the_api_key(office_api):
    client, received = office_api
    assert client.post("/helpline", data=REPORT).status_code == 401
    assert client.post("/uploads", data={"region": "oti", "district": "x", "document_type": "medical_report"},
                       files={"file": ("a.pdf", b"%PDF", "application/pdf")}).status_code == 401
    assert received == []


def test_document_upload_queued(office_api):
    client, received = office_api
    response = client.post("/uploads", data={"region": "oti", "district": "Krachi East",
                                             "document_type": "medical_report", "child_name": "Ama Mensah"},
                           files={"file": ("report.pdf", b"%PDF-1.4", "application/pdf")}, headers=KEY)
    entry, name = received[0]
    assert response.status_code == 202 and response.json()["upload_id"].startswith("UP-")
    assert (entry["child_name"], entry["file"], name) == ("Ama Mensah", "report.pdf", "report.pdf")


@pytest.mark.parametrize("filename,document_type", [("notes.exe", "medical_report"),
                                                    ("sheet.xlsx", "medical_report"),   # a sheet needs its kind
                                                    ("empty.pdf", "medical_report")])
def test_bad_uploads_refused(office_api, filename, document_type):
    client, received = office_api
    content = b"" if filename.startswith("empty") else b"data"
    response = client.post("/uploads", data={"region": "oti", "district": "x", "document_type": document_type},
                           files={"file": (filename, content)}, headers=KEY)
    assert response.status_code == 422 and received == []


# ------------------------------------------------
# Alerts for the dashboard
# ------------------------------------------------

from app.api import alerts  # noqa: E402


@pytest.fixture
def alerts_api(monkeypatch):
    confirmed = []
    monkeypatch.setattr(office, "API_KEY", "test-key")
    monkeypatch.setattr(alerts.notifier, "open_alerts",
                        lambda region: [{"id": 7, "case_ref": "NR-TML-GUM-0001-2026", "region": region}])
    monkeypatch.setattr(alerts.notifier, "confirm",
                        lambda alert_id, by: alert_id == 7 and not confirmed.append((alert_id, by)))
    return TestClient(main.app), confirmed


def test_open_alerts_listed_for_a_region(alerts_api):
    client, _ = alerts_api
    response = client.get("/alerts", params={"region": "Northern"}, headers=KEY)
    assert response.status_code == 200 and response.json()[0]["region"] == "northern"


def test_alerts_need_the_api_key(alerts_api):
    client, confirmed = alerts_api
    assert client.get("/alerts").status_code == 401
    assert client.post("/alerts/7/confirm", json={"confirmed_by": "Team leader"}).status_code == 401
    assert confirmed == []


def test_confirm_an_alert(alerts_api):
    client, confirmed = alerts_api
    response = client.post("/alerts/7/confirm", json={"confirmed_by": "Team leader"}, headers=KEY)
    assert response.status_code == 200 and confirmed == [(7, "Team leader")]


def test_confirm_unknown_or_without_a_name(alerts_api):
    client, _ = alerts_api
    assert client.post("/alerts/99/confirm", json={"confirmed_by": "Team leader"}, headers=KEY).status_code == 404
    assert client.post("/alerts/7/confirm", json={"confirmed_by": ""}, headers=KEY).status_code == 422


def test_alerts_database_down_gives_503(alerts_api, monkeypatch):
    client, _ = alerts_api
    def down(region):
        raise ConnectionError("Postgres is not running")
    monkeypatch.setattr(alerts.notifier, "open_alerts", down)
    assert client.get("/alerts", headers=KEY).status_code == 503


# ------------------------------------------------
# The chat route (the assistant replaced by a fake)
# ------------------------------------------------

import json as json_lines  # noqa: E402

from app.api import chat as chat_api  # noqa: E402
from app.tools.assistant import Reply  # noqa: E402


@pytest.fixture
def chat_client(monkeypatch):
    asked = []
    monkeypatch.setattr(office, "API_KEY", "test-key")
    monkeypatch.setattr(chat_api, "check_ollama", lambda: True)
    def fake_stream(conversation, question, region, approved=None):
        asked.append((conversation, question, region, approved))
        yield "There are 26 "
        yield "High cases."
        yield Reply("There are 26 High cases.", sources=["UE-BLS-SAN-0002-2026"], counts=["26 cases (upper_east)"],
                    citations=["NR-FAKE-1"], invented_citations=["NR-FAKE-1"])
    monkeypatch.setattr(chat_api, "chat_stream", fake_stream)
    return TestClient(main.app), asked


def test_chat_streams_pieces_then_the_checked_reply(chat_client):
    client, asked = chat_client
    response = client.post("/chat", json={"question": "How many High cases?", "region": "Upper East"}, headers=KEY)
    lines = [json_lines.loads(l) for l in response.text.splitlines()]
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/x-ndjson")
    assert [l["piece"] for l in lines[:2]] == ["There are 26 ", "High cases."]
    reply = lines[-1]["reply"]
    assert reply["sources"] == ["UE-BLS-SAN-0002-2026"] and reply["counts"] == ["26 cases (upper_east)"]
    assert asked[0][2] == "upper_east" and reply["conversation"] == asked[0][0]     # a new conversation


def test_chat_without_a_region_is_the_super_administrator(chat_client):
    client, asked = chat_client
    client.post("/chat", json={"question": "How many regions?", "conversation": "c1"}, headers=KEY)
    assert asked[0][:3] == ("c1", "How many regions?", None)


def test_chat_needs_the_api_key_and_a_known_region(chat_client):
    client, asked = chat_client
    assert client.post("/chat", json={"question": "Hello there"}).status_code == 401
    assert client.post("/chat", json={"question": "Hello", "region": "Atlantis"}, headers=KEY).status_code == 422
    assert asked == []


def test_chat_when_ollama_is_down(chat_client, monkeypatch):
    client, _ = chat_client
    monkeypatch.setattr(chat_api, "check_ollama", lambda: False)
    assert client.post("/chat", json={"question": "Hello there"}, headers=KEY).status_code == 503



# ------------------------------------------------
# The dashboard and the case view (the tools, the database and storage replaced by fakes)
# ------------------------------------------------

from app.api import cases as cases_api  # noqa: E402


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *error):
        return False

    def execute(self, sql, params=()):
        self.sql, self.params = sql, params
        return self

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


@pytest.fixture
def cases_client(monkeypatch):
    seen = {"counts": [], "lists": []}
    monkeypatch.setattr(office, "API_KEY", "test-key")
    def fake_count(region, count_by="band", **filters):
        seen["counts"].append((region, count_by, filters))
        return {"region": region or "all regions", "total_cases": 3, "count_by": count_by,
                f"cases_by_{count_by}": {"High": 2, "Low": 1}}
    def fake_list(region, limit=10, **filters):
        seen["lists"].append((region, filters))
        return {"cases": [{"case_ref": "NR-1", "status": filters.get("status")}]}
    monkeypatch.setattr(cases_api, "count_cases", fake_count)
    monkeypatch.setattr(cases_api, "list_cases", fake_list)
    monkeypatch.setattr(cases_api, "show_case", lambda region, ref: {"found": ref == "NR-TML-GUM-0004-2025",
                                                                     "case_ref": ref, "band": "High"})
    rows = {"value": []}
    monkeypatch.setattr(cases_api, "connect", lambda: FakeConnection(rows["value"]))
    files = {"helpline/HL-1.json": b'{"recording_file": "HL-1.m4a"}', "helpline/HL-1.m4a": b"audio",
             "uploads/UP-1/report.pdf": b"%PDF"}
    monkeypatch.setattr(cases_api.storage, "read_bytes", lambda key: files[key])
    monkeypatch.setattr(cases_api.storage, "read_json", lambda key: __import__("json").loads(files[key]))
    return TestClient(main.app), seen, rows


def test_dashboard_for_a_team_leader_counts_by_community(cases_client):
    client, seen, rows = cases_client
    rows["value"] = [{"last": "2026-10-25T01:28:19"}]
    body = client.get("/dashboard", params={"region": "Northern"}, headers=KEY).json()
    assert body["region"] == "northern" and body["last_kobo_submission"] == "2026-10-25T01:28:19"
    assert ("northern", "community", {}) in seen["counts"]
    assert [c["status"] for c in body["kobo_follow_up"]] == ["not_scored_incomplete", "human_review",
                                                              "not_scored_no_consent"]


def test_dashboard_for_the_super_administrator_counts_by_region(cases_client):
    client, seen, rows = cases_client
    rows["value"] = [{"last": None}]
    body = client.get("/dashboard", headers=KEY).json()
    assert body["region"] == "all regions" and (None, "region", {}) in seen["counts"]


def test_one_case_and_not_found(cases_client):
    client, _, _ = cases_client
    assert client.get("/cases/NR-TML-GUM-0004-2025", headers=KEY).json()["band"] == "High"
    assert client.get("/cases/NR-NOPE-0001-2025", headers=KEY).status_code == 404


def test_the_original_with_its_type_and_the_recording(cases_client):
    client, _, rows = cases_client
    rows["value"] = [{"region": "oti", "original_key": "uploads/UP-1/report.pdf"}]
    response = client.get("/cases/OT-1/original", headers=KEY)
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    rows["value"] = [{"region": "oti", "original_key": "helpline/HL-1.json"}]
    response = client.get("/cases/OT-2/original", params={"recording": "true"}, headers=KEY)
    assert response.content == b"audio" and response.headers["content-type"] == "audio/mp4"


def test_no_original_from_another_region_or_without_a_recording(cases_client):
    client, _, rows = cases_client
    rows["value"] = [{"region": "oti", "original_key": "uploads/UP-1/report.pdf"}]
    assert client.get("/cases/OT-1/original", params={"region": "northern"}, headers=KEY).status_code == 404
    rows["value"] = [{"region": "oti", "original_key": "uploads/UP-1/report.pdf"}]
    response = client.get("/cases/OT-1/original", params={"recording": "true"}, headers=KEY)
    assert response.status_code == 404 and response.json()["detail"] == "This case has no recording"


def test_cases_need_the_api_key_and_a_known_region(cases_client):
    client, _, _ = cases_client
    assert client.get("/dashboard").status_code == 401
    assert client.get("/dashboard", params={"region": "Atlantis"}, headers=KEY).status_code == 422
    assert client.get("/cases/NR-1").status_code == 401
