"""
LOAD THE POLICY DOCUMENTS FOR SEARCH

Reads the 8 laws and policies in data/policies, cuts them into chunks of
120 words, embeds them and saves them in Postgres, so the chat can quote
the law. Loading again replaces a document's chunks, so it is safe to rerun
(for example when a policy is updated).

    data/policies/*.pdf -> read_pdf -> chunks (120 / 25) -> embeddinggemma -> Postgres

Run from the project folder (Postgres and Ollama must be running):
    python -m scripts.load_policies
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from app.core.db import connect, create_tables
from app.rag.loaders import read_pdf
from app.services.chunk_store import save_policy_chunks

POLICIES = Path("data/policies")
logging.getLogger("pypdf").setLevel(logging.ERROR)   # font warnings that do not affect the text


def main() -> None:
    create_tables()
    started = time.time()
    total = 0
    for path in sorted(POLICIES.glob("*.pdf")):
        start = time.time()
        text = read_pdf(path)
        saved = save_policy_chunks(path.name, text)
        total += saved
        print(f"{path.name:42} {len(text.split()):7,} words -> {saved:4} chunks  ({time.time() - start:.0f} s)")
    stored = connect().execute(
        "SELECT count(*) AS n, count(DISTINCT document) AS documents FROM chunks WHERE source_type = 'policy'"
    ).fetchone()
    print(f"\n{total} chunks saved in {time.time() - started:.0f} s; "
          f"in the database: {stored['n']} policy chunks from {stored['documents']} documents")


if __name__ == "__main__":
    main()
