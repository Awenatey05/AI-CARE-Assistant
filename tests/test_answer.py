"""The grounded answer: search and the model are replaced by fakes (no Postgres, no Ollama)."""

from __future__ import annotations

import pytest

from app.llm.client import Generation
from app.rag import answer as answer_module
from app.rag.answer import NO_EVIDENCE, answer, cited_labels
from app.rag.embeddings import SearchHit
from app.rag.rag import grounded_prompt

HITS = [SearchHit(1, 0.62, "No person shall force a child to be married.",
                  {"chunk_id": "policy_childrens_act_560.pdf#chunk-16"}),
        SearchHit(2, 0.30, "Her uncle says she will marry after the harvest.",
                  {"chunk_id": "UE-BLS-SAN-0002-2026#chunk-0"})]


@pytest.fixture
def fake(monkeypatch):
    record = {"searched": [], "prompts": [], "reply": "", "hits": HITS}
    def fake_search(question, k, min_score, region):
        record["searched"].append((question, k, min_score, region))
        return record["hits"]
    def fake_chat(messages):
        record["prompts"].append(messages[0]["content"])
        return Generation(record["reply"], "llama3.2", 1.5)
    monkeypatch.setattr(answer_module, "search", fake_search)
    monkeypatch.setattr(answer_module, "chat_with_llm", fake_chat)
    return record


def test_five_chunks_however_weak_by_default(fake):
    fake["reply"] = "Forcing a child to marry is forbidden [policy_childrens_act_560.pdf#chunk-16]."
    answer("Is forced marriage legal?", region="upper_east")
    assert fake["searched"] == [("Is forced marriage legal?", 5, -1.0, "upper_east")]


def test_prompt_is_the_course_grounded_prompt_with_labels(fake):
    fake["reply"] = "x"
    answer("Is forced marriage legal?")
    prompt = fake["prompts"][0]
    assert prompt == grounded_prompt("Is forced marriage legal?", HITS)
    assert "[UE-BLS-SAN-0002-2026#chunk-0 | score=0.300]" in prompt and "I don't have enough evidence" in prompt


def test_real_citations_accepted_and_invented_ones_reported(fake):
    fake["reply"] = ("It is forbidden [policy_childrens_act_560.pdf#chunk-16 | score=0.620]; one girl may be at risk "
                     "[UE-BLS-SAN-0002-2026#chunk-0, policy_uncrc.pdf#chunk-3].")
    result = answer("Is forced marriage legal?")
    assert result.citations == ["policy_childrens_act_560.pdf#chunk-16", "UE-BLS-SAN-0002-2026#chunk-0",
                                "policy_uncrc.pdf#chunk-3"]
    assert result.invented_citations == ["policy_uncrc.pdf#chunk-3"]
    assert result.seconds == 1.5


def test_no_evidence_means_no_model_call(fake):
    fake["hits"] = []
    result = answer("What is the capital of France?")
    assert result.text == NO_EVIDENCE and fake["prompts"] == []


def test_an_answer_without_brackets_has_no_citations():
    assert cited_labels("I don't have enough evidence.") == []


def test_masking_placeholders_are_not_citations():
    assert cited_labels("The caller [NAME] left [PHONE] [NR-1#chunk-0].") == ["NR-1#chunk-0"]


def test_search_tool_keeps_the_region_and_gives_labels(monkeypatch):
    from app.tools import search_tool
    asked = {}
    def fake_search(question, k, min_score, region, source_type):
        asked.update(region=region, k=k, only=source_type)
        return HITS
    monkeypatch.setattr(search_tool, "search", fake_search)
    tool = search_tool.make_search_tool("upper_east")
    result = tool.invoke({"question": "forced marriage", "only": "policy"})
    assert asked == {"region": "upper_east", "k": 5, "only": "policy"}
    assert result["evidence"][0]["label"] == "policy_childrens_act_560.pdf#chunk-16"
