"""Speech-to-text: ffmpeg + Whisper (faster-whisper), run locally.

Recordings are transcribed as English, the organisation's working language,
with no randomness (temperature 0) so the same file always gives the same text.
Whisper does not support Twi or Dagbani: forced into English, it invents
believable English and gets stuck repeating itself. Repeated text compresses
very well, so a high compression ratio marks a transcript that cannot be
trusted. Such a recording is flagged for a person to transcribe, and its
text must not be assessed as if it were what was said.
"""

from __future__ import annotations

import statistics
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel

from config import WHISPER_MODEL

# 1. CONFIGURATION
AUDIO_TYPES = {".m4a", ".mp3", ".wav"}
VIDEO_TYPES = {".mp4", ".mov"}
LANGUAGE = "en"
# Whisper's own limit for repetitive (hallucinated) text. On our 12 recordings,
# English scored 1.40 to 1.54; Dagbani 5.87 and Twi 6.18.
MAX_COMPRESSION_RATIO = 2.4


# 2. LOAD THE MODEL ONCE
@lru_cache(maxsize=2)
def load_model(name: str = WHISPER_MODEL) -> WhisperModel:
    """Load a Whisper model (downloaded on first use, then reused)."""
    return WhisperModel(name, device="cpu", compute_type="int8")


# 3. VIDEO -> AUDIO
def extract_audio(video_path: str | Path, audio_path: str | Path) -> Path:
    """Use ffmpeg to take the sound from a video: one channel, 16 kHz (what Whisper expects)."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", str(audio_path)],
        check=True, capture_output=True,
    )
    return Path(audio_path)


# 4. TRANSCRIBE
def transcribe(path: str | Path, model_name: str = WHISPER_MODEL) -> dict[str, Any]:
    """Transcribe an audio or video file.

    Returns {"text", "compression_ratio", "confidence", "detected_language",
    "duration_s", "needs_human", "reason"}.
    The original file is never changed.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Recording not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in AUDIO_TYPES | VIDEO_TYPES:
        raise ValueError(f"Unsupported recording type: {suffix}")

    with tempfile.TemporaryDirectory() as folder:
        audio = extract_audio(path, Path(folder) / "audio.wav") if suffix in VIDEO_TYPES else path
        segments, info = load_model(model_name).transcribe(str(audio), language=LANGUAGE,
                                                            temperature=0.0)
        segments = list(segments)

    text = " ".join(segment.text.strip() for segment in segments).strip()
    compression = statistics.mean(s.compression_ratio for s in segments) if segments else None
    confidence = statistics.mean(s.avg_logprob for s in segments) if segments else None

    if not text:
        reason = "no speech found"
    elif compression > MAX_COMPRESSION_RATIO:
        reason = "repetitive transcript: possibly a local language; a person must transcribe it"
    else:
        reason = None

    return {
        "text": text,
        "compression_ratio": round(compression, 2) if compression is not None else None,
        "confidence": round(confidence, 2) if confidence is not None else None,   # for information
        "detected_language": info.language,       # for information only: unreliable on accented English
        "duration_s": round(info.duration, 1),
        "needs_human": reason is not None,
        "reason": reason,
    }
