"""Chunking: sizes, overlap and ids."""

from __future__ import annotations

import pytest

from app.rag.rag import chunk_words, make_chunks


def words(n):
    return " ".join(f"w{i}" for i in range(n))


def test_short_case_text_is_one_chunk():
    assert chunk_words(words(82)) == [words(82)]


def test_long_text_overlaps_by_25_words():
    pieces = chunk_words(words(203))
    assert [len(p.split()) for p in pieces] == [120, 108, 13]
    assert pieces[0].split()[-25:] == pieces[1].split()[:25]


def test_empty_text_gives_no_chunks():
    assert chunk_words("   ") == []


def test_chunk_ids_name_the_source():
    chunks = make_chunks([("NR-TML-GUM-0012-2026", words(203)), ("policy_uncrc.pdf", words(10))])
    assert [c.chunk_id for c in chunks] == ["NR-TML-GUM-0012-2026#chunk-0", "NR-TML-GUM-0012-2026#chunk-1",
                                            "NR-TML-GUM-0012-2026#chunk-2", "policy_uncrc.pdf#chunk-0"]


@pytest.mark.parametrize("size,overlap", [(0, 0), (120, 120), (120, -1)])
def test_invalid_sizes_refused(size, overlap):
    with pytest.raises(ValueError):
        chunk_words("a b c", size=size, overlap=overlap)


# ------------------------------------------------
# Embeddings (Ollama replaced by a fake)
# ------------------------------------------------

import requests  # noqa: E402

from app.rag.embeddings import OllamaEmbedder  # noqa: E402


class FakeResponse:
    def __init__(self, texts):
        self.texts = texts

    def raise_for_status(self):
        pass

    def json(self):
        return {"embeddings": [[0.1] * 768 for _ in self.texts]}


def test_one_vector_of_768_numbers_per_text(monkeypatch):
    sent = {}
    def fake_post(url, json, timeout):
        sent.update(url=url, **json)
        return FakeResponse(json["input"])
    monkeypatch.setattr(requests, "post", fake_post)
    vectors = OllamaEmbedder(model="embeddinggemma", base_url="http://ollama:11434/").encode(["a", "b"])
    assert vectors.shape == (2, 768)
    assert sent == {"url": "http://ollama:11434/api/embed", "model": "embeddinggemma", "input": ["a", "b"]}
