"""Reading documents: nothing the answer key relies on may be lost."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.rag.loaders import clean_text, read_document

DATA = Path(__file__).resolve().parent.parent / "data"
TEXT_DOCUMENTS = [".pdf", ".docx"]


def uploads():
    manifest = json.loads((DATA / "uploads" / "uploads_manifest.json").read_text())
    labels = json.loads((DATA / "labels.json").read_text())
    return [(m["file"], labels[m["upload_id"]]) for m in manifest
            if Path(m["file"]).suffix in TEXT_DOCUMENTS]


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text)


@pytest.mark.parametrize("file,label", uploads(), ids=lambda x: x if isinstance(x, str) else "")
def test_every_answer_key_quote_is_in_the_text(file, label):
    text = normalise(read_document(DATA / "uploads" / file))
    for child in label["children"]:
        assert child["name"].split()[0] in text
        for indicator in child["indicators"]:
            assert normalise(indicator["quote"]) in text, indicator["quote"]


def test_six_text_documents_found():
    assert len(uploads()) == 6


def test_clean_text():
    assert clean_text("birth regis-\ntration   was\t done\n\n\n  next line  ") == \
        "birth registration was done\nnext line"


def test_missing_and_unsupported_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_document(tmp_path / "missing.pdf")
    (tmp_path / "photo.jpg").write_bytes(b"")
    with pytest.raises(ValueError):
        read_document(tmp_path / "photo.jpg")
