"""
EMBED SAVED CASES FOR SEARCH

The worker chunks and embeds each case as it saves it. This script does the
same for cases that are saved but not yet searchable: cases saved before the
worker embedded them, or while Ollama was not running. Only masked text is
embedded, under the case reference.

    cases (masked text, no chunks) -> chunks (120 / 25) -> embeddinggemma -> Postgres

Run from the project folder (Postgres and Ollama must be running):
    python -m scripts.embed_cases          # only cases without chunks
    python -m scripts.embed_cases --all    # every case again (after a chunking change)
"""

from __future__ import annotations

import argparse
import time

from app.core.db import connect, create_tables
from app.services.chunk_store import save_case_chunks

MISSING = ("SELECT id, case_ref, region, masked_text FROM cases c WHERE masked_text <> '' "
           "AND NOT EXISTS (SELECT 1 FROM chunks k WHERE k.case_id = c.id) ORDER BY created_at")
EVERY = "SELECT id, case_ref, region, masked_text FROM cases WHERE masked_text <> '' ORDER BY created_at"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="re-embed every case, not only those without chunks")
    args = parser.parse_args()

    create_tables()
    started = time.time()
    cases = connect().execute(EVERY if args.all else MISSING).fetchall()
    total = 0
    for case in cases:
        total += save_case_chunks(case["id"], case["case_ref"], case["region"], case["masked_text"])
    with connect() as c:
        stored = c.execute("SELECT count(*) AS n, count(DISTINCT case_id) AS cases FROM chunks "
                           "WHERE source_type = 'case'").fetchone()
        waiting = c.execute(MISSING).fetchall()
    print(f"{len(cases)} cases embedded: {total} chunks in {time.time() - started:.0f} s")
    print(f"In the database: {stored['n']} case chunks from {stored['cases']} cases; "
          f"{len(waiting)} cases with text still without chunks")


if __name__ == "__main__":
    main()
