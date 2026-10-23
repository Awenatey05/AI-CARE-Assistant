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
