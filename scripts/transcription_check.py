"""
TRANSCRIPTION CHECK

Transcribes the 10 recorded helpline calls and the 2 videos, and compares
each transcript with the reference transcript in data/labels.json.

Pipeline:
    Recording
        |
        v
    transcribe() (ffmpeg + Whisper)
        |
        v
    Compare with reference_transcript
        |
        v
    evaluation/transcription/<model>.csv  (one row per recording)
    evaluation/transcription/summary.csv  (one row per model)

Word error rate (WER) = (words substituted + deleted + inserted) / words in the reference.
0% is a perfect transcript.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import pandas as pd

from app.services.transcription import transcribe
from config import WHISPER_MODEL

# 1. CONFIGURATION
DATA = Path("data")
OUTPUT_DIR = Path("evaluation/transcription")
LOCAL_LANGUAGE = {"HL-2025-0010": "Dagbani", "HL-2025-0044": "Twi"}


# 2. THE RECORDINGS AND THEIR REFERENCE TRANSCRIPTS
def recordings() -> list[dict]:
    labels = json.loads((DATA / "labels.json").read_text())
    calls = json.loads((DATA / "helpline_reports.json").read_text())
    uploads = json.loads((DATA / "uploads" / "uploads_manifest.json").read_text())

    items = [{"id": c["report_id"], "path": DATA / "recordings" / c["recording_file"],
              "reference": labels[c["report_id"]]["reference_transcript"]}
             for c in calls if c["recording_file"]]
    items += [{"id": u["upload_id"], "path": DATA / "uploads" / u["file"],
               "reference": labels[u["upload_id"]]["reference_transcript"]}
              for u in uploads if u["file"].endswith((".mp4", ".mov"))]
    return items


# 3. WORD ERROR RATE
def words(text: str) -> list[str]:
    """Lower case, no punctuation, so only the words are compared."""
    return re.findall(r"[a-z0-9']+", text.lower())


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Edit distance between the two word lists, divided by the reference length."""
    ref, hyp = words(reference), words(hypothesis)
    previous = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, start=1):
        current = [i]
        for j, hyp_word in enumerate(hyp, start=1):
            current.append(min(previous[j] + 1,                            # deleted
                               current[j - 1] + 1,                         # inserted
                               previous[j - 1] + (ref_word != hyp_word)))  # substituted
        previous = current
    return previous[-1] / max(len(ref), 1)


# 4. RUN
def run(model: str) -> pd.DataFrame:
    rows = []
    for item in recordings():
        started = time.perf_counter()
        result = transcribe(item["path"], model_name=model)
        seconds = time.perf_counter() - started
        rows.append({
            "id": item["id"],
            "file": item["path"].name,
            "language": LOCAL_LANGUAGE.get(item["id"], "English"),
            "needs_human": result["needs_human"],
            "compression_ratio": result["compression_ratio"],
            "wer_%": round(100 * word_error_rate(item["reference"], result["text"]), 1),
            "seconds": round(seconds, 1),
            "audio_seconds": result["duration_s"],
            "whisper_text": result["text"],
            "reference_text": item["reference"],
        })
        print(f"  {item['path'].name:18} flagged={str(result['needs_human']):5} WER={rows[-1]['wer_%']:5}%")
    return pd.DataFrame(rows)


def summarise(model: str, results: pd.DataFrame) -> dict:
    english = results[results["language"] == "English"]
    local = results[results["language"] != "English"]
    return {
        "model": model,
        "english_recordings": len(english),
        "english_mean_wer_%": round(english["wer_%"].mean(), 1),
        "english_worst_wer_%": english["wer_%"].max(),
        "english_wrongly_flagged": int(english["needs_human"].sum()),
        "local_language_flagged": f"{int(local['needs_human'].sum())} of {len(local)}",
        "seconds_per_minute_of_audio": round(60 * results["seconds"].sum() / results["audio_seconds"].sum(), 1),
    }


# 5. MAIN PROGRAM
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check Whisper against the reference transcripts")
    parser.add_argument("--model", default=WHISPER_MODEL)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Whisper model: {args.model}")
    results = run(args.model)
    results.to_csv(OUTPUT_DIR / f"{args.model}.csv", index=False)

    summary_path = OUTPUT_DIR / "summary.csv"
    summary = pd.read_csv(summary_path) if summary_path.exists() else pd.DataFrame()
    if not summary.empty:
        summary = summary[summary["model"] != args.model]
    summary = pd.concat([summary, pd.DataFrame([summarise(args.model, results)])], ignore_index=True)
    summary.to_csv(summary_path, index=False)

    print("\n" + summary.to_string(index=False))
    print(f"\nSaved {OUTPUT_DIR / (args.model + '.csv')} and {summary_path}")
