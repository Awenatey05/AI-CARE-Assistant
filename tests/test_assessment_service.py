"""assess_case without Ollama: chat_with_llm is replaced by a fake model with fixed answers."""

from __future__ import annotations

import json

import requests

from app.llm.client import Generation
from app.services import assessment as service
from app.services.assessment import assess_case, present_indicators, quote_in_text

REPORT = ("He said his stepmother hit him with a stick last week and his back is still swollen.\n"
          "He has no birth certificate and the family never registered his birth.")
HIT = "He said his stepmother hit him with a stick last week and his back is still swollen."
BIRTH = "He has no birth certificate and the family never registered his birth."


def answer(present: dict[int, tuple[str | None, str]]) -> str:
    """Build model JSON: present = {indicator: (subtype, quote)}."""
    labels = [{"id": i, "present": i in present,
               "subtype": present[i][0] if i in present else None,
               "quote": present[i][1] if i in present else None} for i in range(1, 11)]
    return json.dumps({"case_id": "wrong-id", "indicators": labels, "summary": "Test."})


def fake_model(monkeypatch, replies):
    """Each call returns the next reply; an Exception in the list is raised instead."""
    calls = []

    def fake_chat(messages, model=None, format=None):
        calls.append(messages)
        reply = replies[len(calls) - 1]
        if isinstance(reply, Exception):
            raise reply
        return Generation(reply, "fake", 0.1)

    monkeypatch.setattr(service, "chat_with_llm", fake_chat)
    return calls


# ------------------------------------------------
# Quote check
# ------------------------------------------------

def test_quote_in_text():
    assert quote_in_text(HIT, REPORT)
    assert quote_in_text("He has no  birth certificate and the family never registered his birth", REPORT)
    assert quote_in_text("he said his stepmother hit him with a stick last week and his back is still swollen.", REPORT)
    assert not quote_in_text("His stepmother beat him every day.", REPORT)


# ------------------------------------------------
# assess_case
# ------------------------------------------------

def test_valid_answer_first_time(monkeypatch):
    fake_model(monkeypatch, [answer({1: (None, HIT), 10: ("a", BIRTH)})])
    result = assess_case("case-1", REPORT)
    assert result["success"] and result["attempts"] == 1
    assert result["data"].case_id == "case-1"          # our ID, not the model's
    assert [i["id"] for i in present_indicators(result["data"])] == [1, 10]


def test_invented_quote_fixed_on_retry(monkeypatch):
    calls = fake_model(monkeypatch, [answer({1: (None, "His stepmother beat him every day.")}),
                                     answer({1: (None, HIT)})])
    result = assess_case("case-1", REPORT)
    assert result["success"] and result["attempts"] == 2
    assert "not in the report" in calls[1][-1]["content"]   # the retry says what was wrong


def test_invalid_twice_could_not_assess(monkeypatch):
    fake_model(monkeypatch, ["not json at all", '{"case_id": "c1", "indicators": []}'])
    result = assess_case("case-1", REPORT)
    assert not result["success"] and result["data"] is None
    assert result["error"] == "Invalid JSON or schema"


def test_model_unavailable_could_not_assess(monkeypatch):
    down = requests.exceptions.ConnectionError("Ollama is not running")
    fake_model(monkeypatch, [down, down])
    result = assess_case("case-1", REPORT)
    assert not result["success"] and result["error"] == "Model unavailable"


def test_other_answer_quote_accepted(monkeypatch):
    other = "The girl was cut by an elder during the ceremony."
    fake_model(monkeypatch, [answer({5: (None, other)})])
    assert assess_case("case-1", REPORT, other_answer=other)["success"]

