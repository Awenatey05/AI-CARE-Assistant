"""Measures for search and grounded answers.

recall_at_k: of the relevant items, how many are in the first k results.
mean_reciprocal_rank: 1 when the first result is relevant, 1/2 when the second is, ... averaged.
citation_precision: of the [citations] in an answer, how many are allowed (were given to the model).
"""

from __future__ import annotations

from collections.abc import Iterable


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")
    return len(set(retrieved_ids[:k]) & relevant_ids) / len(relevant_ids)


def mean_reciprocal_rank(ranked_lists: Iterable[list[str]], relevant_sets: Iterable[set[str]]) -> float:
    scores = []
    for retrieved, relevant in zip(ranked_lists, relevant_sets):
        rank = next((i for i, item in enumerate(retrieved, start=1) if item in relevant), None)
        scores.append(0.0 if rank is None else 1.0 / rank)
    return sum(scores) / len(scores) if scores else 0.0


def citation_precision(answer: str, allowed_ids: set[str]) -> float:
    import re
    cited = re.findall(r"\[([^\]]+)\]", answer)
    return 1.0 if not cited and not allowed_ids else (sum(c in allowed_ids for c in cited) / len(cited) if cited else 0.0)
