"""P5 acceptance: graphiti-export seeding round-trips into a fresh store."""

from __future__ import annotations

import json

from mnemobun.adapters.graphiti_import import SOURCE, seed_from_export
from mnemobun.core.record import STANDING_ACCEPTED


def test_seed_from_export_round_trips(store, tmp_path):
    export = tmp_path / "export"
    export.mkdir()
    (export / "episode.jsonl").write_text(
        "\n".join([
            json.dumps({"uuid": "aaa-1", "content": "User said backups run weekly",
                        "source": "sync_turn", "created_at": "2026-11-01T10:00:00+00:00"}),
            json.dumps({"uuid": "bbb-2", "content": "Agent confirmed btrfs", "source": "sync_turn",
                        "created_at": "2026-11-02T10:00:00+00:00"}),
        ]),
        encoding="utf-8",
    )
    (export / "entity.jsonl").write_text(
        json.dumps({"uuid": "ccc-3", "name": "backups",
                    "summary": "Backups protect /var", "created_at": "2026-11-01T10:00:00+00:00"}),
        encoding="utf-8",
    )
    (export / "edges.jsonl").write_text(
        "\n".join([
            json.dumps({"id": 1, "rel": "MENTIONS", "src": "aaa-1", "dst": "ccc-3",
                        "created_at": "", "fact": ""}),
            json.dumps({"id": 2, "rel": "RELATES_TO", "src": "ccc-3", "dst": "aaa-1",
                        "created_at": "", "fact": "Backups depend on the weekly schedule"}),
        ]),
        encoding="utf-8",
    )
    counts = seed_from_export(store, export)
    assert counts == {"episodes": 2, "entities": 1, "claims": 1, "links": 1}

    episode = store.find("epi-aaa-1")
    assert episode is not None and episode.type == "event"
    assert SOURCE in episode.body
    assert "backups run weekly" in episode.body
    assert episode.links == ["ent-ccc-3"]

    claim = store.find("rel-00000002")
    assert claim is not None and claim.type == "claim"
    assert claim.standing == STANDING_ACCEPTED

    entity = store.find("ent-ccc-3")
    assert entity is not None and "protect /var" in entity.abstract


def test_seed_is_idempotent_on_names(store, tmp_path, config, clock):
    export = tmp_path / "export"
    export.mkdir()
    (export / "episode.jsonl").write_text(
        json.dumps({"uuid": "aaa-1", "content": "one", "source": "", "created_at": ""}),
        encoding="utf-8",
    )
    from mnemobun.core.store import Store

    first = seed_from_export(store, export)
    second_store = Store(tmp_path / "again", config=config, clock=clock, agent="test-agent")
    second_store.init()
    again = seed_from_export(second_store, export)
    assert first["episodes"] == 1
    assert again["episodes"] == 1  # update-in-place path, no duplicate files
