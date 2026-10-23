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
