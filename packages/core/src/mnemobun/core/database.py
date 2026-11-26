"""The index database. Every table here is a cache — deleting the file loses no knowledge.

Two text surfaces: the active surface (default retrieval) and the history surface (only
`--as-of` reads it). A row in records exists for invalid files too,
so supersede chains resolve without touching the tree.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from .paths import StoreLayout

SURFACE_ACTIVE = "chunks"
SURFACE_HISTORY = "history"

SCHEMA_VERSION = 4
WRITER_VERSION = "0.3.0"
HANDSHAKE_FILENAME = "handshake.json"


SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS files (
        path TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        indexed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS records (
        name TEXT PRIMARY KEY,
        path TEXT NOT NULL,
        type TEXT NOT NULL,
        abstract TEXT NOT NULL,
        created TEXT NOT NULL,
        updated TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        invalid_at TEXT,
        superseded_by TEXT,
        standing TEXT NOT NULL,
        usage REAL NOT NULL,
        importance REAL NOT NULL DEFAULT 0,
        writer TEXT NOT NULL,
        links TEXT NOT NULL,
        provenance TEXT NOT NULL
    )
    """,
    f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS {SURFACE_ACTIVE} USING fts5(
        name UNINDEXED,
        kind UNINDEXED,
        anchor UNINDEXED,
        heading,
        text
    )
    """,
    f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS {SURFACE_HISTORY} USING fts5(
        name UNINDEXED,
        kind UNINDEXED,
        anchor UNINDEXED,
        heading,
        text
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vector_files (
        path TEXT PRIMARY KEY,
        content_hash TEXT NOT NULL,
        model TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vector_chunks (
        path TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        anchor TEXT NOT NULL,
        heading TEXT NOT NULL,
        embedding BLOB NOT NULL,
        PRIMARY KEY(path, chunk_index)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS access_log (
        at TEXT NOT NULL,
        name TEXT NOT NULL,
        query TEXT NOT NULL,
        kind TEXT NOT NULL,
        writer TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS standing_history (
        claim TEXT NOT NULL,
        from_standing TEXT,
        to_standing TEXT NOT NULL,
        cause TEXT NOT NULL,
        at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)


class Database:
    def __init__(self, layout: StoreLayout):
        self._layout = layout

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self._layout.index_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._layout.index_db)
        connection.row_factory = sqlite3.Row
        try:
            columns = connection.execute("PRAGMA table_info(records)").fetchall()
            if columns and any(column["name"] == "status" for column in columns):
                connection.execute("ALTER TABLE records DROP COLUMN status")
            if columns and not any(column["name"] == "standing" for column in columns):
                connection.execute(
                    "ALTER TABLE records ADD COLUMN standing TEXT NOT NULL"
                    " DEFAULT 'accepted'"
                )
            if columns and not any(column["name"] == "usage" for column in columns):
                connection.execute(
                    "ALTER TABLE records ADD COLUMN usage REAL NOT NULL"
                    " DEFAULT 1.0"
                )
            if columns and not any(column["name"] == "importance" for column in columns):
                connection.execute(
                    "ALTER TABLE records ADD COLUMN importance REAL NOT NULL"
                    " DEFAULT 0.0"
                )
            if columns and any(column["name"] == "weight" for column in columns):
                connection.execute("ALTER TABLE records DROP COLUMN weight")
            connection.execute("DROP TABLE IF EXISTS raw_chunks")
            for statement in SCHEMA:
                connection.execute(statement)
            self._handshake(connection)
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _handshake(self, connection: sqlite3.Connection) -> None:
        """Plugin<->store version handshake: drift is a named error, not a crash."""
        from .errors import StoreVersionError

        state = self._layout.root / ".state"
        path = state / HANDSHAKE_FILENAME
        if not path.exists():
            state.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {"schema_version": SCHEMA_VERSION, "writer_version": WRITER_VERSION}
                ),
                encoding="utf-8",
            )
            return
        known = json.loads(path.read_text(encoding="utf-8"))
        schema = int(known.get("schema_version", SCHEMA_VERSION))
        if schema > SCHEMA_VERSION:
            raise StoreVersionError(
                f"store version {schema} written by plugin "
                f"{known.get('writer_version', 'unknown')}; this plugin is "
                f"{WRITER_VERSION} (schema {SCHEMA_VERSION}) — run index rebuild / "
                "migration or start from scratch"
            )
        if schema < SCHEMA_VERSION or known.get("writer_version") != WRITER_VERSION:
            path.write_text(
                json.dumps(
                    {"schema_version": SCHEMA_VERSION, "writer_version": WRITER_VERSION}
                ),
                encoding="utf-8",
            )

    def drop(self) -> None:
        self._layout.index_db.unlink(missing_ok=True)
