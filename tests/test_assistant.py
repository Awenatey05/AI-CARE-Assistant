"""The assistant loop: a scripted fake model and fake tools (no Ollama, no database)."""

from __future__ import annotations

import json
from typing import Literal

import pytest
from pydantic import BaseModel

from app.llm.client import Generation
from app.tools import assistant
from app.tools.agents import Tool


class CountArgs(BaseModel):
    band: Literal["No risk", "Low", "Moderate", "High"] | None = None


class NameArgs(BaseModel):
    name: str


class ShowArgs(BaseModel):
    case_ref: str


@pytest.fixture
def run(monkeypatch):
    record = {"regions": [], "ran": [], "sent": []}
    def case_tools(region):
        record["regions"].append(region)
        def count(band=None):
            record["ran"].append(("count_cases", band))
            return {"total": 26, "cases": [{"case_ref": "UE-BLS-SAN-0002-2026"}]}
        def by_name(name):
            record["ran"].append(("find_case_by_name", name))
            return {"found": 1, "cases": [{"case_ref": "UE-BLS-FUM-0001-2026"}]}
        def show(case_ref):
            record["ran"].append(("show_case", case_ref))
            return {"found": True, "case_ref": case_ref, "band": "High"}
        return [Tool("count_cases", "Count cases.", CountArgs, count),
                Tool("show_case", "Show one case.", ShowArgs, show),
                Tool("find_case_by_name", "Find by name.", NameArgs, by_name, requires_approval=True)]
    monkeypatch.setattr(assistant, "mask_keeping_names", lambda text: (text, []))   # replaced in the masking tests
    monkeypatch.setattr(assistant, "make_case_tools", case_tools)
    monkeypatch.setattr(assistant, "make_search_tool", lambda region: Tool(
        "search_documents", "Search.", NameArgs, lambda name: {"evidence": [{"label": "policy_uncrc.pdf#chunk-3"}]}))

    def go(script, question="How many High cases?", **options):
        replies = iter(script)
        def fake_chat(messages, format=None):
            record["sent"].append([m["content"] for m in messages])
            return Generation(next(replies), "llama3.2", 1.0)
        monkeypatch.setattr(assistant, "chat_with_llm", fake_chat)
        monkeypatch.setattr(assistant, "stream_chat_with_llm", lambda messages: iter(["The streamed answer."]))
        return assistant.ask(question, "upper_east", **options)
    return go, record


def tool(tool_name, **args):
    return json.dumps({"tool": tool_name, "args": args})


def answer(text):
    return json.dumps({"answer": text})


def test_tool_then_answer_with_a_real_citation(run):
    go, record = run
    reply = go([tool("count_cases", band="High"), answer("There are 26 High cases, e.g. [UE-BLS-SAN-0002-2026].")])
    assert reply.text.startswith("There are 26") and record["ran"] == [("count_cases", "High")]
    assert reply.citations == ["UE-BLS-SAN-0002-2026"] and reply.invented_citations == []
    assert record["regions"] == ["upper_east"]
    assert '"total": 26' in record["sent"][1][-1]                      # the result went back to the model


def test_invented_citation_is_reported(run):
    go, _ = run
    reply = go([tool("count_cases", band="High"), answer("See [NR-TML-GUM-0012-2026].")])
    assert reply.invented_citations == ["NR-TML-GUM-0012-2026"]


def test_wrong_arguments_go_back_to_the_model(run):
    go, record = run
    reply = go([tool("count_cases", band="Very high"), tool("count_cases", band="High"), answer("26.")])
    assert record["ran"] == [("count_cases", "High")]
    assert "were wrong" in record["sent"][1][-1] and reply.tool_calls[0]["error"]


def test_unknown_tool_and_bad_json_are_corrected(run):
    go, record = run
    reply = go(["not json at all", tool("delete_everything"), tool("count_cases"), answer("26.")])
    assert reply.text == "26." and record["ran"] == [("count_cases", None)]
    assert "ONE JSON object" in record["sent"][1][-1] and "no tool called" in record["sent"][2][-1]


def test_name_lookup_waits_for_the_ok(run):
    go, record = run
    reply = go([tool("find_case_by_name", name="Ama")], question="Do we have a case for Ama?")
    assert reply.needs_approval == {"tool": "find_case_by_name", "args": {"name": "Ama"}} and record["ran"] == []
    reply = go([tool("find_case_by_name", name="Ama"), answer("Yes: [UE-BLS-FUM-0001-2026].")],
               question="Do we have a case for Ama?", approved=reply.needs_approval)
    assert record["ran"] == [("find_case_by_name", "Ama")] and reply.invented_citations == []


def test_the_budget_stops_a_loop(run):
    go, record = run
    bands = ["High", "Low", "Moderate", "No risk", "High", "Low"]
    reply = go([tool("count_cases", band=band) for band in bands])       # a different call each time
    assert reply.text == assistant.COULD_NOT_FINISH and reply.stopped_reason == "tool-call budget exhausted"
    assert len(record["ran"]) == 4


def test_instructions_list_every_tool_and_the_rules(run):
    go, record = run
    go([answer("I don't have enough evidence.")])
    system = record["sent"][0][0]
    assert all(name in system for name in ("count_cases", "find_case_by_name", "search_documents"))
    assert "Never guess" in system and "phone number" in system


def test_a_reference_in_the_question_is_looked_up_first(run):
    go, record = run
    reply = go([answer("It is High [NR-SGN-SAG-0001-2025].")], question="Why is nr-sgn-sag-0001-2025 High?")
    assert record["ran"] == [("show_case", "NR-SGN-SAG-0001-2025")]
    assert '"band": "High"' in record["sent"][0][-1] and reply.invented_citations == []


def test_empty_values_removed_and_high_risk_read_as_high(run):
    go, record = run
    go([tool("count_cases", band="high risk", channel="all", region="oti"), answer("26.")])
    assert record["ran"] == [("count_cases", "High")]


def test_sources_shown_even_when_the_model_cites_none(run):
    go, _ = run
    reply = go([tool("count_cases", band="High"), answer("There are 26.")])
    assert reply.citations == [] and reply.with_sources() == "There are 26.\n\nSources: [UE-BLS-SAN-0002-2026]"



def test_the_model_never_sees_the_name_but_the_tool_gets_it(run, monkeypatch):
    go, record = run
    monkeypatch.setattr(assistant, "mask_keeping_names",
                        lambda text: (text.replace("Ama Mensah", "[NAME]"), ["Ama Mensah"]))
    question = "Do we have a case for Ama Mensah?"
    first = go([tool("find_case_by_name", name="[NAME]")], question=question)
    assert first.needs_approval == {"tool": "find_case_by_name", "args": {"name": "[NAME]"}}
    reply = go([tool("find_case_by_name", name="[NAME]"), answer("Yes: [UE-BLS-FUM-0001-2026].")],
               question=question, approved=first.needs_approval)
    assert record["ran"] == [("find_case_by_name", "Ama Mensah")]            # the database got the real name
    assert all("Ama" not in text for sent in record["sent"] for text in sent)  # the model never did
    assert reply.tool_calls == [{"tool": "find_case_by_name", "args": {"name": "[NAME]"}}]


def test_a_reference_survives_masking(run, monkeypatch):
    go, record = run
    monkeypatch.setattr(assistant, "mask_keeping_names", lambda text: ("[PHONE] [NAME]", []))   # masking too much
    go([answer("High.")], question="Why is NR-SGN-SAG-0001-2025 High?")
    assert record["ran"] == [("show_case", "NR-SGN-SAG-0001-2025")]


# ------------------------------------------------
# One chat turn (chat memory and ask() replaced by fakes)
# ------------------------------------------------

@pytest.fixture
def turn(monkeypatch):
    saved, asked = [], []
    store = {"last_refs": []}
    monkeypatch.setattr(assistant.chat_store, "recent_messages", lambda c: [{"role": "user", "content": "earlier"}])
    monkeypatch.setattr(assistant.chat_store, "last_case_refs", lambda c: store["last_refs"])
    monkeypatch.setattr(assistant.chat_store, "add_user_message", lambda c, r, m: saved.append(("user", m)))
    monkeypatch.setattr(assistant.chat_store, "add_assistant_message",
                        lambda c, r, m, refs: saved.append(("assistant", m, refs)))
    monkeypatch.setattr(assistant, "mask_keeping_names", lambda text: (text.replace("Ama Mensah", "[NAME]"), []))
    reply = {"value": assistant.Reply("It is High.", sources=["NR-SGN-SAG-0001-2025", "policy_uncrc.pdf#chunk-3"])}
    def fake_ask_stream(question, region, approved=None, history=None, extra_refs=None):
        asked.append({"question": question, "history": history, "extra_refs": extra_refs})
        yield reply["value"]
    monkeypatch.setattr(assistant, "ask_stream", fake_ask_stream)
    return saved, asked, store, reply


def test_history_is_sent_and_both_messages_saved_masked(turn):
    saved, asked, _, _ = turn
    assistant.chat("c1", "Is there a case for Ama Mensah?", "northern")
    assert asked[0]["history"] == [{"role": "user", "content": "earlier"}]
    assert saved == [("user", "Is there a case for [NAME]?"),
                     ("assistant", "It is High.", ["NR-SGN-SAG-0001-2025"])]      # case references only


def test_this_case_uses_the_one_case_of_the_last_answer(turn):
    _, asked, store, _ = turn
    store["last_refs"] = ["NR-SGN-SAG-0001-2025"]
    assistant.chat("c1", "Explain further why this case is High.", "northern")
    assert asked[0]["extra_refs"] == ["NR-SGN-SAG-0001-2025"]


def test_this_case_is_not_guessed_when_the_last_answer_had_several(turn):
    _, asked, store, _ = turn
    store["last_refs"] = ["NR-TML-GUM-0002-2025", "NR-TML-GUM-0004-2025"]
    assistant.chat("c1", "Tell me more about this case.", "northern")
    assert asked[0]["extra_refs"] == []


def test_nothing_saved_while_waiting_for_the_ok(turn):
    saved, _, _, reply = turn
    reply["value"] = assistant.Reply("This looks up a child's name. Continue?",
                                     needs_approval={"tool": "find_case_by_name", "args": {"name": "[NAME]"}})
    assistant.chat("c1", "Is there a case for Ama Mensah?", "northern")
    assert saved == []


def test_nothing_saved_when_ollama_fails(turn, monkeypatch):
    saved, _, _, _ = turn
    def ollama_down(*args, **kwargs):
        raise ConnectionError("Ollama is not running")
    monkeypatch.setattr(assistant, "ask_stream", ollama_down)
    with pytest.raises(ConnectionError):
        assistant.chat("c1", "How many High cases?", "northern")
    assert saved == []



def test_counted_line_shows_what_the_tool_really_counted():
    reply = assistant.Reply("We work in 6 regions.", counts=[assistant.describe_count(
        {"count_by": "region", "number_of_regions": 6, "total_cases": 1173, "region": "all regions", "filters": {}})])
    assert reply.with_sources() == "We work in 6 regions.\nCounted: 6 regions, 1173 cases (all regions)"
    by_band = assistant.describe_count({"count_by": "band", "total_cases": 102, "region": "northern",
                                        "filters": {"band": "No risk"}})
    assert by_band == "102 cases (northern, band No risk)"
    one = assistant.describe_count({"count_by": "region", "number_of_regions": 1, "total_cases": 269,
                                    "region": "northern", "filters": {}})
    assert one == "1 region, 269 cases (northern)"


def test_the_prompt_tells_the_model_the_users_region(run):
    go, record = run
    go([answer("One region.")])
    assert "user's region (upper_east)" in record["sent"][0][0]



# ------------------------------------------------
# Streaming: the answer arrives piece by piece, and is checked and saved at the end
# ------------------------------------------------

def test_ready_then_the_answer_is_streamed_and_checked(run, monkeypatch):
    go, record = run
    pieces = ["There are 26 ", "High cases ", "[UE-BLS-SAN-0002-2026]", " and [NR-FAKE-0001-2026]."]
    sent_for_answer = []
    def fake_stream(messages):
        sent_for_answer.append(messages[-1]["content"])
        yield from pieces
    monkeypatch.setattr(assistant, "stream_chat_with_llm", fake_stream)
    replies = iter([tool("count_cases", band="High"), json.dumps({"ready": True})])
    monkeypatch.setattr(assistant, "chat_with_llm", lambda messages, format=None: Generation(next(replies), "m", 1.0))
    items = list(assistant.ask_stream("How many High cases?", "upper_east"))
    assert items[:-1] == pieces                                       # each piece, as it arrives
    reply = items[-1]
    assert reply.text == "There are 26 High cases [UE-BLS-SAN-0002-2026] and."   # checked: the invention removed
    assert reply.invented_citations == ["NR-FAKE-0001-2026"]          # checked after the last piece
    assert "plain text, not JSON" in sent_for_answer[0]
    assert "Current question:\n\nHow many High cases?" in sent_for_answer[0]      # the question it must answer


def test_ask_gives_only_the_checked_reply(run):
    go, _ = run
    reply = go([tool("count_cases", band="High"), answer("26.")])
    assert isinstance(reply, assistant.Reply) and reply.text == "26."


def test_the_turn_is_saved_only_after_the_last_piece(turn, monkeypatch):
    saved, _, _, reply = turn
    def pieces(question, region, approved=None, history=None, extra_refs=None):
        yield "It is "
        assert saved == []                                            # nothing saved while it is written
        yield "High."
        yield assistant.Reply("It is High.", sources=["NR-SGN-SAG-0001-2025"])
    monkeypatch.setattr(assistant, "ask_stream", pieces)
    items = list(assistant.chat_stream("c1", "Why is it High?", "northern"))
    assert items[:2] == ["It is ", "High."] and saved[-1] == ("assistant", "It is High.", ["NR-SGN-SAG-0001-2025"])



def test_the_same_tool_call_again_leads_to_the_answer(run):
    go, record = run
    reply = go([tool("count_cases", band="High"), tool("count_cases", band="High")])
    assert reply.text == "The streamed answer." and reply.stopped_reason is None
    assert record["ran"] == [("count_cases", "High")]                  # the tool ran once



def test_an_invented_citation_is_never_shown_as_a_source():
    reply = assistant.Reply("Six regions [NR-TML-...].", citations=["NR-TML-..."], invented_citations=["NR-TML-..."],
                            sources=[])
    assert "Sources" not in reply.with_sources()
    mixed = assistant.Reply("See [NR-1] and [NR-FAKE].", citations=["NR-1", "NR-FAKE"], invented_citations=["NR-FAKE"])
    assert mixed.with_sources().endswith("Sources: [NR-1]")



def test_bracketed_text_that_is_not_a_reference_is_removed():
    allowed = {"NR-SGN-SAG-0001-2025", "policy_uncrc.pdf#chunk-3"}
    text = ('It is High [NR-SGN-SAG-0001-2025]: "afraid at night" [indicator 1, "found_in": "report"]. '
            'Six regions [cases_by_region northern 269]. Call [PHONE]. See [policy_uncrc.pdf#chunk-3].')
    assert assistant.without_invented(text, allowed) == ('It is High [NR-SGN-SAG-0001-2025]: "afraid at night". '
                                                         'Six regions. Call [PHONE]. See [policy_uncrc.pdf#chunk-3].')


def test_the_reply_is_cleaned_but_the_invention_is_still_reported(run, monkeypatch):
    run[0]([answer("x")])                                              # sets up the fake tools
    replies = iter([tool("count_cases", band="High"), json.dumps({"ready": True})])
    monkeypatch.setattr(assistant, "chat_with_llm", lambda messages, format=None: Generation(next(replies), "m", 1.0))
    monkeypatch.setattr(assistant, "stream_chat_with_llm",
                        lambda messages: iter(["26 [UE-BLS-SAN-0002-2026] [NR-FAKE-1]."]))
    reply = assistant.ask("How many High cases?", "upper_east")
    assert reply.text == "26 [UE-BLS-SAN-0002-2026]." and reply.invented_citations == ["NR-FAKE-1"]
    assert reply.citations == ["UE-BLS-SAN-0002-2026"]
