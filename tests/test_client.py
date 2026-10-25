"""The Ollama client's streaming, with a fake Ollama (no model is called)."""

from __future__ import annotations

import json

from app.llm import client


class FakeStream:
    """What requests returns for a streamed answer: one JSON line per piece."""
    def __enter__(self):
        return self

    def __exit__(self, *error):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        for piece in ["The ", "law ", ""]:
            yield json.dumps({"message": {"content": piece}}).encode()
        yield b""


def test_streaming_yields_each_piece(monkeypatch):
    sent = {}
    def fake_post(url, json, timeout, stream):
        sent.update(url=url, stream_body=json["stream"], stream=stream)
        return FakeStream()
    monkeypatch.setattr(client.requests, "post", fake_post)
    assert list(client.stream_chat_with_llm([{"role": "user", "content": "x"}])) == ["The ", "law "]
    assert sent["stream_body"] is True and sent["stream"] is True and sent["url"].endswith("/api/chat")
