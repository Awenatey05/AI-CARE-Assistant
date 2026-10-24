"""The search tool: the cases (of the user's region) and the policies, by meaning.

For questions about the law, or about what reports say, that the case tools
cannot count or list. Returns the closest chunks with their labels, which
the answer must cite in [brackets]; only masked text is returned.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.rag.answer import K, MIN_SCORE
from app.rag.search import search
from app.tools.agents import Tool


class SearchArgs(BaseModel):
    question: str = Field(min_length=3, description="what to look for, in plain words")
    only: str | None = Field(default=None, pattern="^(case|policy)$", description="'case' or 'policy' to search one kind")


def search_documents(region: str | None, question: str, only: str | None = None) -> dict[str, Any]:
    hits = search(question, k=K, min_score=MIN_SCORE, region=region, source_type=only)
    return {"evidence": [{"label": hit.metadata["chunk_id"], "score": round(hit.score, 3), "text": hit.text}
                         for hit in hits]}


def make_search_tool(region: str | None) -> Tool:
    return Tool("search_documents", "Search the case reports (your region) and the 8 laws and policies by "
                "meaning. Use it for what the law says, or what reports describe. Cite the labels in [brackets].",
                SearchArgs, lambda question, only=None: search_documents(region, question, only))
