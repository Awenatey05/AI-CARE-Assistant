"""Search: the chunks closest in meaning to a question (pgvector).

Does the job of the course's SemanticIndex.search(k, min_score), but in
Postgres: the question is embedded and compared with every chunk by cosine
similarity, using the HNSW index. Results are SearchHit objects, so the
course's format_context() and grounded_prompt() can use them unchanged.

With a region, only that region's cases are searched; policies are always
included, because the law applies everywhere.
"""

from __future__ import annotations

import psycopg

from app.core.db import connect
from app.rag.embeddings import OllamaEmbedder, SearchHit


def search(question: str, k: int = 3, min_score: float = -1.0, region: str | None = None,
           source_type: str | None = None, embedder: OllamaEmbedder | None = None,
           connection: psycopg.Connection | None = None) -> list[SearchHit]:
    """The k chunks most similar to the question, best first, with a score of at least min_score."""
    vector = (embedder or OllamaEmbedder()).encode([question])[0]
    where, params = ["1 - (embedding <=> %(v)s) >= %(min)s"], {"v": vector, "min": min_score, "k": k}
    if region:
        where.append("(source_type = 'policy' OR region = %(region)s)")
        params["region"] = region
    if source_type:
        where.append("source_type = %(type)s")
        params["type"] = source_type
    own = connection is None
    connection = connection or connect()
    try:
        rows = connection.execute(
            "SELECT id, text, section, document, source_type, case_id, region, "
            "1 - (embedding <=> %(v)s) AS score FROM chunks "
            f"WHERE {' AND '.join(where)} ORDER BY embedding <=> %(v)s LIMIT %(k)s", params).fetchall()
    finally:
        if own:
            connection.close()
    return [SearchHit(row["id"], float(row["score"]), row["text"],
                      {"chunk_id": row["section"], "document": row["document"], "source_type": row["source_type"],
                       "case_id": row["case_id"], "region": row["region"]})
            for row in rows]
