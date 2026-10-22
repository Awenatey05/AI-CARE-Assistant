"""Database connection and tables (PostgreSQL + pgvector).

Every part of the application gets its connection from here, so the
database address lives in one place (DATABASE_URL in .env).
"""

from __future__ import annotations

from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from config import DATABASE_URL

SCHEMA = Path(__file__).parent / "schema.sql"


def connect() -> psycopg.Connection:
    """Open a connection. Rows come back as dictionaries; vectors as numpy arrays."""
    connection = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    register_vector(connection)
    return connection


def create_tables() -> None:
    """Create the tables if they do not exist yet, and load the place codes.
    Safe to run at every start: nothing is created twice and no code is changed."""
    from app.services.case_ref import load_place_codes

    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(SCHEMA.read_text())
        load_place_codes(connection)
