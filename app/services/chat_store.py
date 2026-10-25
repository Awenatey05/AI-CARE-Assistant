"""Chat memory, saved in Postgres.

The model remembers nothing by itself: the application keeps the conversation
and sends it with every question. The conversation is kept in the
chat_messages table, so it survives a restart.

    conversation history
            ↓
        the assistant
            ↓
        response
            ↓
    conversation history

Questions are saved masked ([NAME], [PHONE]), so no child's name is stored.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.db import connect

# 1. CONFIGURATION
RECENT_EXCHANGES = 3   # questions and answers sent to the model each time (the context window)


# 2. CREATE A NEW CONVERSATION
def create_conversation() -> str:
    """Start a new conversation and return its id."""
    return str(uuid.uuid4())


# 3. ADD A USER MESSAGE
def add_user_message(conversation: str, region: str | None, message: str) -> None:
    """Add the (masked) user question to the conversation."""
    connect_and_add(conversation, region, "user", message, [])


# 4. ADD AN ASSISTANT MESSAGE
def add_assistant_message(conversation: str, region: str | None, message: str, case_refs: list[str]) -> None:
    """Add the assistant's answer, with the case references it used (for "this case")."""
    connect_and_add(conversation, region, "assistant", message, case_refs)


def connect_and_add(conversation: str, region: str | None, role: str, message: str, case_refs: list[str]) -> None:
    with connect() as connection:
        connection.execute("INSERT INTO chat_messages (session_id, region, role, content, case_refs) "
                           "VALUES (%s, %s, %s, %s, %s)", (conversation, region, role, message, case_refs))


# 5. THE CONVERSATION SENT TO THE MODEL
def recent_messages(conversation: str, exchanges: int = RECENT_EXCHANGES) -> list[dict[str, str]]:
    """The last few questions and answers, oldest first. Older messages are kept but not
    sent, so the conversation never grows past the model's context window."""
    rows = connect().execute(
        "SELECT role, content FROM chat_messages WHERE session_id = %s ORDER BY id DESC LIMIT %s",
        (conversation, exchanges * 2)).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


def last_case_refs(conversation: str) -> list[str]:
    """The case references in the last answer: what "this case" refers to."""
    row = connect().execute("SELECT case_refs FROM chat_messages WHERE session_id = %s AND role = 'assistant' "
                            "ORDER BY id DESC LIMIT 1", (conversation,)).fetchone()
    return row["case_refs"] if row else []


# 6. DISPLAY CONVERSATION HISTORY
def show_history(conversation: str) -> list[dict[str, Any]]:
    """Every message stored for this conversation."""
    return connect().execute("SELECT role, content, case_refs, created_at FROM chat_messages "
                             "WHERE session_id = %s ORDER BY id", (conversation,)).fetchall()


# 7. SHOW MEMORY STATISTICS
def show_statistics(conversation: str) -> dict[str, int]:
    """How many questions and answers this conversation has."""
    rows = connect().execute("SELECT role, count(*) AS n FROM chat_messages WHERE session_id = %s GROUP BY role",
                             (conversation,)).fetchall()
    counts = {row["role"]: row["n"] for row in rows}
    return {"user messages": counts.get("user", 0), "assistant messages": counts.get("assistant", 0),
            "total messages": sum(counts.values())}


# 8. CLEAR
def clear_conversation(conversation: str) -> str:
    """Forget a conversation and start a new one."""
    with connect() as connection:
        connection.execute("DELETE FROM chat_messages WHERE session_id = %s", (conversation,))
    return create_conversation()
