"""Transcription without Whisper: the model is replaced by a fake with fixed segments."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import transcription
from app.services.transcription import MAX_COMPRESSION_RATIO, transcribe


class FakeModel:
    def __init__(self, segments):
        self.segments = segments
        self.calls = []

    def transcribe(self, audio, language, temperature):
        self.calls.append((audio, language, temperature))
        info = SimpleNamespace(language="yo", duration=12.3)
        return iter(self.segments), info


def segment(text, compression_ratio=1.5, avg_logprob=-0.3):
    return SimpleNamespace(text=text, compression_ratio=compression_ratio, avg_logprob=avg_logprob)


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "HL-test.m4a"
    path.write_bytes(b"fake audio")
    return path


def use(monkeypatch, segments):
    model = FakeModel(segments)
    monkeypatch.setattr(transcription, "load_model", lambda name=None: model)
    return model


def test_confident_english_is_trusted(monkeypatch, recording):
    model = use(monkeypatch, [segment(" Hello, good morning."), segment(" She went to bed hungry.")])
    result = transcribe(recording)
    assert result["text"] == "Hello, good morning. She went to bed hungry."
    assert not result["needs_human"]
    assert model.calls[0][1:] == ("en", 0.0)         # always English, no randomness
    assert result["detected_language"] == "yo"       # kept for information only


def test_repetitive_transcript_flagged_for_a_person(monkeypatch, recording):
    use(monkeypatch, [segment(" I have a very good boy. I have a very good boy.", MAX_COMPRESSION_RATIO + 3)])
    result = transcribe(recording)
    assert result["needs_human"] and "local language" in result["reason"]


def test_no_speech_flagged(monkeypatch, recording):
    use(monkeypatch, [])
    result = transcribe(recording)
    assert result["needs_human"] and result["reason"] == "no speech found"


def test_video_sound_is_extracted_first(monkeypatch, tmp_path):
    video = tmp_path / "OFF-test.mp4"
    video.write_bytes(b"fake video")
    extracted = []
    monkeypatch.setattr(transcription, "extract_audio", lambda v, a: extracted.append(v) or a)
    model = use(monkeypatch, [segment(" Good afternoon.")])
    transcribe(video)
    assert extracted == [video] and model.calls[0][0].endswith("audio.wav")


def test_missing_and_unsupported_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        transcribe(tmp_path / "missing.m4a")
    (tmp_path / "notes.txt").write_text("not audio")
    with pytest.raises(ValueError):
        transcribe(tmp_path / "notes.txt")
