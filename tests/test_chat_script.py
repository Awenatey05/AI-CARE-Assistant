"""The terminal chat's printing (no model, no database)."""

from __future__ import annotations

from app.tools.assistant import Reply
from scripts.chat import show_answer


def test_streamed_pieces_are_printed_as_they_arrive(capsys):
    reply = show_answer(iter(["There are ", "26.", Reply("There are 26.")]))
    assert reply.text == "There are 26." and capsys.readouterr().out.endswith("There are 26.")


def test_an_answer_that_was_not_streamed_is_still_printed(capsys):
    show_answer(iter([Reply("I could not finish this; please ask in a simpler way.")]))
    assert "I could not finish this" in capsys.readouterr().out


def test_nothing_extra_is_printed_while_waiting_for_the_ok(capsys):
    reply = show_answer(iter([Reply("Continue?", needs_approval={"tool": "find_case_by_name", "args": {}})]))
    assert reply.needs_approval and "Continue?" not in capsys.readouterr().out
