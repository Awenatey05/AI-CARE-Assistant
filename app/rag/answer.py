"""A grounded answer: search, then the model answers from the evidence only.

    question -> search (5 closest chunks) -> grounded_prompt -> llama3.2 -> answer + citation check

The prompt tells the model to use only the evidence, to cite it in [brackets]
and to say "I don't have enough evidence" when it cannot answer. Python then
checks every citation: a label that is not one of the chunks the model was
given is reported as invented.

All 5 closest chunks are given to the model, however low their score
(min_score -1.0): in child protection it is safer for the model to read a
chunk that does not help than to hide one about a child at risk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.llm.client import chat_with_llm
from app.rag.embeddings import SearchHit
from app.rag.rag import grounded_prompt
from app.rag.search import search

# 1. SETTINGS
K = 5              # chunks given to the model
MIN_SCORE = -1.0   # keep all k, however weak (see above)
NO_EVIDENCE = "I don't have enough evidence."
PLACEHOLDERS = {"NAME", "PHONE"}   # left by masking; not citations


@dataclass
class Answer:
    text: str
    hits: list[SearchHit]
    citations: list[str] = field(default_factory=list)
    invented_citations: list[str] = field(default_factory=list)
    seconds: float = 0.0


# 2. CITATIONS
def cited_labels(text: str) -> list[str]:
    """The labels cited in [brackets], e.g. [NR-TML-GUM-0012-2026#chunk-0].
    A copied score ("| score=0.512") is ignored; [a, b] counts as two labels;
    the masking placeholders [NAME] and [PHONE] are not citations."""
    labels = []
    for inside in re.findall(r"\[([^\[\]]+)\]", text):
        for label in re.split(r"[,;]", inside):
            label = label.split("|")[0].strip()
            if label and label not in PLACEHOLDERS and label not in labels:
                labels.append(label)
    return labels


# 3. ANSWER
def answer(question: str, region: str | None = None, k: int = K, min_score: float = MIN_SCORE) -> Answer:
    """Answer one question from the cases (of one region, if given) and the policies."""
    hits = search(question, k=k, min_score=min_score, region=region)
    if not hits:
        return Answer(NO_EVIDENCE, hits)
    reply = chat_with_llm([{"role": "user", "content": grounded_prompt(question, hits)}])
    given = {hit.metadata["chunk_id"] for hit in hits}
    citations = cited_labels(reply.text)
    return Answer(reply.text, hits, citations, [c for c in citations if c not in given], reply.latency_s)
