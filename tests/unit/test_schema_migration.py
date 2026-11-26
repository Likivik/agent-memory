"""Schema drift must never crash a store again (P13.6 lesson)."""

import sqlite3

from mnemobun.core import frontmatter
from mnemobun.core.config import Config
from mnemobun.core.database import Database
from mnemobun.core.paths import StoreLayout
from mnemobun.core.record import MemoryRecord
from mnemobun.core.store import Store


def test_old_frontmatter_weight_still_reads():
    text = frontmatter.render(
        {
            "name": "note-x",
            "type": "fact",
            "abstract": "a",
            "weight": 2.5,
            "standing": "accepted",
            "created": "2026-01-01T00:00:00+00:00",
            "updated": "2026-01-01T00:00:00+00:00",
        },
        "",
    )
    parsed = MemoryRecord.from_text(text)
    assert parsed.usage == 2.5
    assert parsed.importance == 0.0


def test_index_created_by_old_code_is_migrated(tmp_path):
    store = Store(tmp_path / "s", config=Config.default(), writer="t")
    store.init()
    with sqlite3.connect(store.layout.index_db) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(records)")]
    assert "usage" in columns
    assert "importance" in columns

    legacy = tmp_path / "legacy"
    (legacy / ".index").mkdir(parents=True)
    with sqlite3.connect(legacy / ".index" / "index.db") as connection:
        connection.execute(
            "CREATE TABLE records (name TEXT PRIMARY KEY, weight REAL NOT NULL)"
        )
        connection.execute("INSERT INTO records VALUES ('a', 2.0)")
    database = Database(StoreLayout(legacy, Config.default()))
    with database.connect() as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(records)")]
        assert "usage" in columns
        assert "importance" in columns
        assert "weight" not in columns
