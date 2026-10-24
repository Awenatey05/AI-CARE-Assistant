"""Chunking and the grounded prompt (from the course's rag.py).

Texts are cut into pieces of 120 words, each overlapping the one before by
25 words, so a sentence on a boundary is never lost. Each piece gets an id
like policy_childrens_act_560.pdf#chunk-37 or NR-TML-GUM-0012-2026#chunk-0,
which answers cite in [brackets].
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.rag.embeddings import SearchHit


@dataclass
class Chunk:
    text: str
    source: str
    chunk_id: str


def chunk_words(text: str, *, size: int = 120, overlap: int = 25) -> list[str]:
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Require size > 0 and 0 <= overlap < size")
    words = text.split()
    step = size - overlap
    return [" ".join(words[start:start + size]) for start in range(0, len(words), step) if words[start:start + size]]


def make_chunks(documents: Iterable[tuple[str, str]], size: int = 120, overlap: int = 25) -> list[Chunk]:
    chunks: list[Chunk] = []
    for source, text in documents:
        for number, body in enumerate(chunk_words(text, size=size, overlap=overlap)):
            chunks.append(Chunk(body, source, f"{source}#chunk-{number}"))
    return chunks


def format_context(hits: list[SearchHit]) -> str:
    return "\n\n".join(f"[{hit.metadata.get('chunk_id', hit.index)} | score={hit.score:.3f}]\n{hit.text}" for hit in hits)


def grounded_prompt(question: str, hits: list[SearchHit]) -> str:
    context = format_context(hits)
    return f"""Answer the question using only the evidence below.
If the evidence is insufficient, say: I don't have enough evidence.
Cite claims with the source labels in square brackets. Do not invent citations.

EVIDENCE
{context}

QUESTION
{question}
"""
