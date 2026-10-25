"""Masking: names and phone numbers are hidden, and nothing else in the evidence changes."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.rag.loaders import read_document
from app.services.masking import mask

DATA = Path(__file__).resolve().parent.parent / "data"


def test_names_and_phone_masked():
    text = "Brought by Mrs. Hawa Musah, 055 000 3471. Examined by: Nurse Patience Dery."
    assert mask(text) == "Brought by Mrs. [NAME], [PHONE]. Examined by: Nurse [NAME]."


def test_known_names_always_masked():
    """Names the system knows for the case are masked even if spaCy misses them."""
    text = "Comfort said she has not eaten since Monday."
    assert mask(text, known_names=["Comfort Atinga"]) == "[NAME] said she has not eaten since Monday."


def test_ordinary_words_are_not_names():
    """Matching is case-sensitive: words like 'comfort' and 'he had' are not masked."""
    text = "He told the nurse he had not eaten. She needs comfort and patience."
    assert mask(text, known_names=["Comfort Atinga", "Patience Dery"]) == text


def test_empty_text():
    assert mask("") == ""


def documents():
    manifest = json.loads((DATA / "uploads" / "uploads_manifest.json").read_text())
    labels = json.loads((DATA / "labels.json").read_text())
    return [(m["file"], labels[m["upload_id"]]) for m in manifest if m["file"].endswith((".pdf", ".docx"))]


@pytest.mark.parametrize("file,label", documents(), ids=lambda x: x if isinstance(x, str) else "")
def test_documents_masked_without_losing_evidence(file, label):
    known = [child["name"] for child in label["children"]]
    masked = mask(read_document(DATA / "uploads" / file), known_names=known)

    # no phone number and no part of the child's name is left
    assert not re.search(r"\b0\d{2} \d{3} \d{4}\b", masked)
    for name in known:
        for part in name.split():
            assert not re.search(rf"\b{part}\b", masked), part

    # every evidence sentence is still there, with only the names replaced
    flat = " ".join(masked.split())
    for child in label["children"]:
        for indicator in child["indicators"]:
            quote = " ".join(indicator["quote"].split())
            for name in known:
                for part in name.split():
                    quote = re.sub(rf"\b{part}\b", "[NAME]", quote)
            assert quote.replace("[NAME] [NAME]", "[NAME]") in flat.replace("[NAME] [NAME]", "[NAME]")



def test_mask_keeping_names_returns_the_names_it_removed():
    from app.services.masking import mask_keeping_names
    masked, names = mask_keeping_names("Do we have a case for the girl of Mrs Ama Mensah? Call 024 412 3456.")
    assert "Ama" not in masked and "[NAME]" in masked and "[PHONE]" in masked
    assert names == ["Ama Mensah"]
