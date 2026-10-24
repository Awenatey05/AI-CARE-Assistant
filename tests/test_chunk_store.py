"""Saving chunks in the real Postgres database (rolled back after each test), with a fake embedder.

Skipped if Postgres is not running.
"""

from __future__ import annotations

import numpy as np
import psycopg
import pytest

from app.core.db import connect, create_tables
from app.services.case_store import save_case
from app.services.chunk_store import save_case_chunks, save_policy_chunks


class FakeEmbedder:
    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(len(texts))
        return np.ones((len(texts), 768), dtype=np.float32)


@pytest.fixture
def db():
    try:
        create_tables()
        connection = connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running (docker compose up -d)")
    save_case({"id": "test-chunk-1", "channel": "field", "region": "northern", "status": "assessed",
               "child_name": "Ama Mensah", "masked_text": "x"}, connection=connection)
    yield connection
    connection.rollback()
    connection.close()


def rows(db, where, args):
    return db.execute(f"SELECT * FROM chunks WHERE {where} ORDER BY id", args).fetchall()


def words(n):
    return " ".join(f"w{i}" for i in range(n))


def test_case_chunks_named_by_reference_with_region(db):
    assert save_case_chunks("test-chunk-1", "NR-TML-GUM-0001-2026", "northern", "<PERSON> " + words(150),
                            embedder=FakeEmbedder(), connection=db) == 2
    saved = rows(db, "case_id = %s", ("test-chunk-1",))
    assert [r["section"] for r in saved] == ["NR-TML-GUM-0001-2026#chunk-0", "NR-TML-GUM-0001-2026#chunk-1"]
    assert {(r["source_type"], r["document"], r["region"]) for r in saved} == {
        ("case", "NR-TML-GUM-0001-2026", "northern")}
    assert len(saved[0]["embedding"].to_list()) == 768
    assert all("Ama" not in r["text"] for r in saved)


def test_saving_again_replaces_old_chunks(db):
    save_case_chunks("test-chunk-1", "NR-1", "northern", words(150), embedder=FakeEmbedder(), connection=db)
    save_case_chunks("test-chunk-1", "NR-1", "northern", words(10), embedder=FakeEmbedder(), connection=db)
    assert len(rows(db, "case_id = %s", ("test-chunk-1",))) == 1


def test_empty_text_saves_nothing_and_does_not_call_ollama(db):
    embedder = FakeEmbedder()
    assert save_case_chunks("test-chunk-1", "NR-1", "northern", None, embedder=embedder, connection=db) == 0
    assert embedder.calls == []


def test_policy_chunks_have_no_case_or_region_and_are_embedded_in_batches(db):
    embedder = FakeEmbedder()
    assert save_policy_chunks("test_policy.pdf", words(95 * 40), embedder=embedder, connection=db) == 40
    saved = rows(db, "document = %s", ("test_policy.pdf",))
    assert {(r["source_type"], r["case_id"], r["region"]) for r in saved} == {("policy", None, None)}
    assert embedder.calls == [32, 8]
    save_policy_chunks("test_policy.pdf", words(10), embedder=embedder, connection=db)
    assert len(rows(db, "document = %s", ("test_policy.pdf",))) == 1
