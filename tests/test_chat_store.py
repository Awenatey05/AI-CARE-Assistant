"""Chat memory in the real Postgres database. The functions share the test's connection,
so everything is rolled back at the end. Skipped if Postgres is not running."""

from __future__ import annotations

import psycopg
import pytest

from app.core.db import connect, create_tables
from app.services import chat_store


class Shared:
    """The test's connection, lent to chat_store: 'with' and close() leave it open."""
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        return self

    def __exit__(self, *error):
        return False

    def close(self):
        pass


@pytest.fixture
def store(monkeypatch):
    try:
        create_tables()
        connection = connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running (docker compose up -d)")
    monkeypatch.setattr(chat_store, "connect", lambda: Shared(connection))
    yield chat_store
    connection.rollback()
    connection.close()


def talk(store, conversation, exchanges):
    for number in range(exchanges):
        store.add_user_message(conversation, "northern", f"question {number}")
        store.add_assistant_message(conversation, "northern", f"answer {number}", [f"NR-{number}"])


def test_only_the_last_three_exchanges_are_sent_oldest_first(store):
    conversation = store.create_conversation()
    talk(store, conversation, 5)
    sent = store.recent_messages(conversation)
    assert [m["content"] for m in sent] == ["question 2", "answer 2", "question 3", "answer 3", "question 4", "answer 4"]
    assert [m["role"] for m in sent[:2]] == ["user", "assistant"]
    assert len(store.show_history(conversation)) == 10                 # everything is still kept


def test_the_case_of_the_last_answer(store):
    conversation = store.create_conversation()
    assert store.last_case_refs(conversation) == []
    talk(store, conversation, 2)
    assert store.last_case_refs(conversation) == ["NR-1"]


def test_conversations_are_kept_apart(store):
    first, second = store.create_conversation(), store.create_conversation()
    talk(store, first, 2)
    assert store.recent_messages(second) == []


def test_statistics_and_clear(store):
    conversation = store.create_conversation()
    talk(store, conversation, 2)
    assert store.show_statistics(conversation) == {"user messages": 2, "assistant messages": 2, "total messages": 4}
    new = store.clear_conversation(conversation)
    assert new != conversation and store.show_history(conversation) == []
