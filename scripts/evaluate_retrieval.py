"""
EVALUATE SEARCH AND GROUNDED ANSWERS

Asks 11 questions about the law. For each, the policies are searched (5 chunks,
as the chat's search tool does) and the documents found are compared with the
law that answers the question: recall at 1 and at 5, and the mean reciprocal
rank. The model then answers from those chunks, and the citations in its
answer are checked (citation precision).

    questions -> search (pgvector) -> grounded answer -> evaluation/rag/retrieval.txt
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.llm.client import chat_with_llm
from app.rag.evaluation import citation_precision, mean_reciprocal_rank, recall_at_k
from app.rag.rag import grounded_prompt
from app.rag.search import search

logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)
OUTPUT = Path("evaluation/rag/retrieval.txt")
K = 5

QUESTIONS = [
    ("What does the law say about forcing a child into marriage?", "policy_childrens_act_560.pdf"),
    ("What is the minimum age for marriage?", "policy_childrens_act_560.pdf"),
    ("Can a child be made to work at night?", "policy_childrens_act_560.pdf"),
    ("Is it a crime to traffic a child?", "policy_human_trafficking_act_694.pdf"),
    ("Is it legal to recruit a child for labour in another town?", "policy_human_trafficking_act_694.pdf"),
    ("What protection is there against violence in the home?", "policy_domestic_violence_act_732.pdf"),
    ("What is the punishment for defilement of a child?", "policy_criminal_offences_act_29.pdf"),
    ("How should a child in conflict with the law be treated?", "policy_justice_for_children_2015.pdf"),
    ("Why does birth registration matter for children's welfare?", "policy_child_family_welfare_2015.pdf"),
    ("Does every child have a right to education?", "policy_uncrc.pdf"),
    ("What did the Children's (Amendment) Act change?", "policy_childrens_amendment_act_937.pdf"),
]


def documents_in_order(hits) -> list[str]:
    """The documents of the chunks found, best first, each once."""
    return list(dict.fromkeys(hit.metadata["document"] for hit in hits))


def main() -> None:
    lines, ranked, relevant, recall_1, recall_5, precision = ["SEARCH AND GROUNDED ANSWERS", ""], [], [], [], [], []
    for number, (question, law) in enumerate(QUESTIONS, 1):
        hits = search(question, k=K, source_type="policy")
        found = documents_in_order(hits)
        ranked.append(found)
        relevant.append({law})
        recall_1.append(recall_at_k(found, {law}, 1))
        recall_5.append(recall_at_k(found, {law}, K))
        answer = chat_with_llm([{"role": "user", "content": grounded_prompt(question, hits)}]).text
        precision.append(citation_precision(answer, {hit.metadata["chunk_id"] for hit in hits}))
        lines += [f"{number}. {question}",
                  f"   the right law: {law}",
                  f"   found, best first: {', '.join(found)}",
                  f"   right law first: {'yes' if recall_1[-1] else 'no'};  in the top {K} chunks: {'yes' if recall_5[-1] else 'no'};"
                  f"  citation precision: {precision[-1]:.2f}",
                  f"   answer: {' '.join(answer.split())[:220]}", ""]
    lines += [f"recall@1 (the right law first):        {sum(recall_1) / len(recall_1):.2f}",
              f"recall@{K} (the right law in the top {K}): {sum(recall_5) / len(recall_5):.2f}",
              f"mean reciprocal rank:                  {mean_reciprocal_rank(ranked, relevant):.2f}",
              f"citation precision (average):          {sum(precision) / len(precision):.2f}"]
    OUTPUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
