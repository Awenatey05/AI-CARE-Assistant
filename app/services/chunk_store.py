"""Saving searchable chunks (Postgres + pgvector).

Each case's masked text and each policy document is cut into chunks of
120 words (app/rag/rag.py), embedded (app/rag/embeddings.py) and saved in
the chunks table with its vector. A case chunk is named by the case
reference, never by the child's name, and only masked text is saved.
Saving again replaces the old chunks, so a re-processed case or a
re-loaded policy never leaves duplicates.
"""

from __future__ import annotations

import psycopg

from app.core.db import connect
from app.rag.embeddings import OllamaEmbedder
from app.rag.rag import Chunk, make_chunks

BATCH = 32   # chunks sent to Ollama in one request


# 1. EMBED AND INSERT
def _insert(connection: psycopg.Connection, chunks: list[Chunk], source_type: str, case_id: str | None,
            region: str | None, embedder: OllamaEmbedder) -> int:
    for start in range(0, len(chunks), BATCH):
        batch = chunks[start:start + BATCH]
        vectors = embedder.encode([c.text for c in batch])
        for chunk, vector in zip(batch, vectors):
            connection.execute(
                "INSERT INTO chunks (case_id, source_type, document, section, region, text, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (case_id, source_type, chunk.source, chunk.chunk_id, region, chunk.text, vector))
    return len(chunks)


def _save(delete_sql: str, delete_args: tuple, chunks: list[Chunk], source_type: str, case_id: str | None,
          region: str | None, embedder: OllamaEmbedder | None, connection: psycopg.Connection | None) -> int:
    own = connection is None
    connection = connection or connect()
    try:
        connection.execute(delete_sql, delete_args)
        saved = _insert(connection, chunks, source_type, case_id, region, embedder or OllamaEmbedder()) if chunks else 0
        if own:
            connection.commit()
        return saved
    finally:
        if own:
            connection.close()


# 2. A CASE
def save_case_chunks(case_id: str, case_ref: str, region: str | None, masked_text: str | None,
                     embedder: OllamaEmbedder | None = None, connection: psycopg.Connection | None = None) -> int:
    """Chunk, embed and save one case's masked text. Returns the number of chunks."""
    chunks = make_chunks([(case_ref, masked_text or "")])
    return _save("DELETE FROM chunks WHERE case_id = %s", (case_id,),
                 chunks, "case", case_id, region, embedder, connection)


# 3. A POLICY DOCUMENT
def save_policy_chunks(document: str, text: str, embedder: OllamaEmbedder | None = None,
                       connection: psycopg.Connection | None = None) -> int:
    """Chunk, embed and save one policy document. Returns the number of chunks."""
    chunks = make_chunks([(document, text)])
    return _save("DELETE FROM chunks WHERE source_type = 'policy' AND document = %s", (document,),
                 chunks, "policy", None, None, embedder, connection)
