"""The chat for the Streamlit chat page: questions answered as they are written.

The answer is streamed as one JSON line per piece, the way Ollama streams it:
    {"piece": "There are 26 "}
    {"piece": "High-risk cases..."}
    {"reply": {"text": ..., "sources": ..., "counts": ..., "needs_approval": ..., "conversation": ...}}
The last line has the checked reply: the sources and counts to show under the
answer, and, for a name lookup, the tool call waiting for the user's OK (the
page then sends the question again with "approved"). Needs the API key
(X-Api-Key), like the other office routes.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.office import check_api_key, check_region
from app.llm.client import check_ollama
from app.services import chat_store
from app.tools.assistant import Reply, chat_stream

router = APIRouter(tags=["chat"])


class ChatQuestion(BaseModel):
    question: str = Field(min_length=2)
    region: str | None = Field(default=None, description="the user's region; empty for the super administrator")
    conversation: str | None = Field(default=None, description="empty to start a new conversation")
    approved: dict[str, Any] | None = Field(default=None, description="the tool call the user said OK to")


def line(data: dict[str, Any]) -> str:
    return json.dumps(data, default=str, ensure_ascii=False) + "\n"


@router.post("/chat")
def chat_route(body: ChatQuestion, x_api_key: Annotated[str | None, Header()] = None) -> StreamingResponse:
    """Answer one question, streamed as it is written; the checked reply follows at the end."""
    check_api_key(x_api_key)
    region = check_region(body.region) if body.region else None
    if not check_ollama():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The assistant is not available now")
    conversation = body.conversation or chat_store.create_conversation()

    def pieces():
        for item in chat_stream(conversation, body.question, region, approved=body.approved):
            if isinstance(item, Reply):
                real = [c for c in item.citations if c not in item.invented_citations]   # never an invented source
                yield line({"reply": {"text": item.text, "sources": real or item.sources[:10],
                                      "counts": item.counts, "needs_approval": item.needs_approval,
                                      "invented_citations": item.invented_citations,
                                      "conversation": conversation}})
            else:
                yield line({"piece": item})

    return StreamingResponse(pieces(), media_type="application/x-ndjson")
