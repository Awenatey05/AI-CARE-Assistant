"""
EVALUATE SEARCH AND GROUNDED ANSWERS

Asks 11 questions about the law. For each, the policies are searched (5 chunks,
as the chat's search tool does) and the documents found are compared with the
law that answers the question: recall at 1 and at 5, and the mean reciprocal
rank. The model then answers from those chunks, and the citations in its
answer are checked (citation precision), twice: strictly, citation by citation
as written, and as the application reads them (a copied score such as
"| score=0.415" removed, as cited_labels() does).

Question 9 accepts two laws: the Child and Family Welfare Policy, and Article 7
of the UN Convention, which also covers birth registration. The results are
given with this key and with the first, stricter key (one law per question).

    questions -> search (pgvector) -> grounded answer -> evaluation/rag/retrieval.txt
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.llm.client import chat_with_llm
from app.rag.answer import cited_labels
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
    ("Why does birth registration matter for children's welfare?",
     "policy_child_family_welfare_2015.pdf", "policy_uncrc.pdf"),
    ("Does every child have a right to education?", "policy_uncrc.pdf"),
    ("What did the Children's (Amendment) Act change?", "policy_childrens_amendment_act_937.pdf"),
]


def documents_in_order(hits) -> list[str]:
    """The documents of the chunks found, best first, each once."""
    return list(dict.fromkeys(hit.metadata["document"] for hit in hits))


def as_read_by_the_app(answer: str, allowed: set[str]) -> float:
    """Citation precision on the labels the application reads (a copied score removed)."""
    cited = cited_labels(answer)
    return sum(label in allowed for label in cited) / len(cited) if cited else 0.0


def average(values: list[float]) -> float:
    return sum(values) / len(values)


def main() -> None:
    lines = ["SEARCH AND GROUNDED ANSWERS", ""]
    ranked, keys, strict_keys, r1, r5, s1, s5, strict, read = [], [], [], [], [], [], [], [], []
    for number, (question, *laws) in enumerate(QUESTIONS, 1):
        hits = search(question, k=K, source_type="policy")
        found = documents_in_order(hits)
        key, strict_key = set(laws), {laws[0]}
        ranked.append(found); keys.append(key); strict_keys.append(strict_key)
        r1.append(min(1.0, recall_at_k(found, key, 1) * len(key)))       # any right law first
        r5.append(min(1.0, recall_at_k(found, key, K) * len(key)))       # any right law in the top K
        s1.append(recall_at_k(found, strict_key, 1)); s5.append(recall_at_k(found, strict_key, K))
        answer = chat_with_llm([{"role": "user", "content": grounded_prompt(question, hits)}]).text
        allowed = {hit.metadata["chunk_id"] for hit in hits}
        strict.append(citation_precision(answer, allowed)); read.append(as_read_by_the_app(answer, allowed))
        lines += [f"{number}. {question}",
                  f"   the right law: {' or '.join(laws)}",
                  f"   found, best first: {', '.join(found)}",
                  f"   right law first: {'yes' if r1[-1] else 'no'};  in the top {K} chunks: {'yes' if r5[-1] else 'no'};"
                  f"  citation precision: {strict[-1]:.2f} strict, {read[-1]:.2f} as read by the app",
                  f"   answer: {' '.join(answer.split())[:220]}", ""]
    lines += ["                                     answer key   first, stricter key",
              f"recall@1 (a right law first):          {average(r1):.2f}         {average(s1):.2f}",
              f"recall@{K} (a right law in the top {K}):  {average(r5):.2f}         {average(s5):.2f}",
              f"mean reciprocal rank:                  {mean_reciprocal_rank(ranked, keys):.2f}         "
              f"{mean_reciprocal_rank(ranked, strict_keys):.2f}",
              "",
              f"citation precision, strict:            {average(strict):.2f}",
              f"citation precision, as read by the app: {average(read):.2f}"]
    OUTPUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
