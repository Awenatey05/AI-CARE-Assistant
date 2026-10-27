"""The danger words that raise an alert for text that could not be assessed."""

from __future__ import annotations

from app.services.rules import danger_words


def test_danger_words_found_as_whole_words_ignoring_capitals():
    assert danger_words("Her uncle BEAT her.") == ["1"]
    assert danger_words("She will be married after the harvest; an agent came.") == ["5", "6"]
    assert danger_words("He said he wants to die.") == ["self_harm"]


def test_no_danger_words_in_ordinary_text():
    assert danger_words("An unbeatable football team; she agreed to marrying later never.") == []
    assert danger_words("") == [] and danger_words(None) == []
