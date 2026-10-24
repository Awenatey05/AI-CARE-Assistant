"""Search in the real Postgres database (rolled back after each test), with a fake embedder
whose vectors point in chosen directions, so the expected order is known."""

from __future__ import annotations

import numpy as np
import psycopg
import pytest

from app.core.db import connect, create_tables
from app.rag.search import search
from app.services.case_store import save_case

DIRECTIONS = {"marriage": 0, "school": 1, "labour": 2}


def vector_for(text):
    v = np.full(768, 0.01, dtype=np.float32)
    for word, axis in DIRECTIONS.items():
        if word in text:
            v[axis] = 1.0
    return v


class FakeEmbedder:
    def encode(self, texts):
        return np.stack([vector_for(t) for t in texts])


@pytest.fixture
def db():
    try:
        create_tables()
        connection = connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running (docker compose up -d)")
    connection.execute("DELETE FROM chunks")          # only this test's chunks; the rollback restores them
    for case_id, region in (("test-search-nr", "northern"), ("test-search-ot", "oti")):
        save_case({"id": case_id, "channel": "field", "region": region, "status": "assessed"}, connection=connection)
    rows = [("test-search-nr", "case", "NR-1", "northern", "the girl is out of school"),
            ("test-search-ot", "case", "OT-1", "oti", "the boy left school for labour"),
            (None, "policy", "policy_act.pdf", None, "no school child shall be forced into marriage")]
    for case_id, kind, document, region, text in rows:
        connection.execute(
            "INSERT INTO chunks (case_id, source_type, document, section, region, text, embedding) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (case_id, kind, document, f"{document}#chunk-0", region, text, vector_for(text)))
    yield connection
    connection.rollback()
    connection.close()


def ask(db, question, **options):
    return search(question, embedder=FakeEmbedder(), connection=db, **options)


def test_best_match_first_with_its_citation_label(db):
    hits = ask(db, "marriage", k=1)
    assert [h.metadata["chunk_id"] for h in hits] == ["policy_act.pdf#chunk-0"]
    assert 0 < hits[0].score <= 1


def test_region_filter_keeps_policies_but_hides_other_regions(db):
    found = {h.metadata["document"] for h in ask(db, "school", k=10, region="northern")}
    assert found == {"NR-1", "policy_act.pdf"}


def test_min_score_leaves_out_weak_matches(db):
    assert len(ask(db, "school", k=10)) == 3
    strong = ask(db, "labour", k=10, min_score=0.6)
    assert [h.metadata["document"] for h in strong] == ["OT-1"]


def test_only_policies_or_only_cases(db):
    assert {h.metadata["source_type"] for h in ask(db, "school", k=10, source_type="policy")} == {"policy"}
