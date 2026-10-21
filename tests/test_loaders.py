"""Reading documents: nothing the answer key relies on may be lost."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.rag.loaders import clean_text, read_document, read_excel_rows

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


# ------------------------------------------------
# Excel: one row per child
# ------------------------------------------------

EXCEL_FILES = {"attendance_register_kanvili.xlsx": 15, "ccpc_log_builsa.xlsx": 8,
               "field_round_2025_r2_west_gonja.xlsx": 20}


@pytest.mark.parametrize("file,children", EXCEL_FILES.items())
def test_excel_one_row_per_child(file, children):
    rows = read_excel_rows(DATA / "uploads" / file)
    assert len(rows) == children                      # title, blank rows and footer skipped

    manifest = json.loads((DATA / "uploads" / "uploads_manifest.json").read_text())
    upload_id = next(m["upload_id"] for m in manifest if m["file"] == file)
    names = {child["name"] for child in json.loads((DATA / "labels.json").read_text())[upload_id]["children"]}
    found = {value for row in rows for value in row.values() if isinstance(value, str)}
    assert names <= found                             # every child in the answer key has a row
