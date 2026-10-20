"""The Ollama client, tested without Ollama: requests.post is replaced by a fake."""

from __future__ import annotations

import pytest
import requests

from app.llm import client
from app.llm.client import chat_with_llm, check_ollama, parse_json_object


# ------------------------------------------------
# parse_json_object: model text -> Python dict
# ------------------------------------------------

@pytest.mark.parametrize("text", [
    '{"case_id": "c1"}',
    '```json\n{"case_id": "c1"}\n```',                # Markdown fences
    'Here is the result:\n{"case_id": "c1"}\nDone.',  # prose around the JSON
])
def test_parse_json_object_accepts(text):
    assert parse_json_object(text) == {"case_id": "c1"}


@pytest.mark.parametrize("text", ["no json here", "[1, 2, 3]", '{"case_id": '])
def test_parse_json_object_rejects(text):
    with pytest.raises(ValueError):
        parse_json_object(text)


# ------------------------------------------------
# chat_with_llm: request sent to Ollama
# ------------------------------------------------

class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.exceptions.HTTPError(f"{self.status} error")

    def json(self):
        return self.payload


def test_chat_sends_messages_and_returns_text(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        sent.update(url=url, body=json)
        return FakeResponse({"message": {"role": "assistant", "content": "  hello  "}})

    monkeypatch.setattr(client.requests, "post", fake_post)
    messages = [{"role": "system", "content": "You are an assessor."},
                {"role": "user", "content": "Read this report."}]
    result = chat_with_llm(messages, model="llama3.2", temperature=0, format="json")

    assert result.text == "hello"
    assert sent["url"].endswith("/api/chat")
    assert sent["body"]["messages"] == messages
    assert sent["body"]["stream"] is False
    assert sent["body"]["format"] == "json"
    assert sent["body"]["options"]["temperature"] == 0


def test_chat_raises_when_ollama_fails(monkeypatch):
    monkeypatch.setattr(client.requests, "post",
                        lambda url, json, timeout: FakeResponse({}, status=404))
    with pytest.raises(requests.exceptions.HTTPError):
        chat_with_llm([{"role": "user", "content": "hi"}])


def test_check_ollama_false_when_unreachable(monkeypatch):
    def fake_get(url, timeout):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(client.requests, "get", fake_get)
    assert check_ollama() is False
