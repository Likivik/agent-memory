"""Seed a store from a FalkorDB graphiti export (P5).

Input: the JSONL files produced by the export in ~/.hermes/memory-export/ (README.md there
documents the pipeline): episodes.jsonl (raw turns), entities.jsonl (node summaries),
edges.jsonl (MENTIONS / RELATES_TO with optional fact text).

Mapping (design doc §11 step 3):
- episodes  -> type "event", one record per episode, provenance `graphiti-import`,
  body keeps the full content and the graphiti uuid.
- entities  -> type "entity", abstract = summary (trimmed), provenance `graphiti-import`.
- RELATES_TO edges with fact text -> type "claim", standing accepted (they were the live
  memory of record at cutover), provenance `graphiti-import`; MENTIONS and bare edges
  become links on the source record where both endpoints are imported.

Names are slugged from the graphiti uuid to stay collision-free and traceable.
"""

from __future__ import annotations

import json
import pathlib

from agent_memory.core.store import Store

SOURCE = "graphiti-import"
BATCH = 500


def _slug(prefix: str, uuid: str) -> str:
    return f"{prefix}-{uuid[:12]}"


def _edge_key(edge_id: object) -> str:
    if isinstance(edge_id, int):
        return f"{edge_id:08x}"
    return str(edge_id)[:12]


def seed_from_export(store: Store, export_dir: pathlib.Path) -> dict[str, int]:
    counts = {"episodes": 0, "entities": 0, "claims": 0, "links": 0}
    index: dict[str, str] = {}  # graphiti uuid -> record name

    episodes_path = export_dir / "episodes.jsonl"
    if episodes_path.exists():
        specs: list[dict[str, object]] = []
        for line in episodes_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            name = _slug("epi", row["uuid"])
            index[row["uuid"]] = name
            content = row.get("content") or ""
            specs.append({
                "abstract": (" ".join(content.split())[: store.config.storage.abstract_max_chars]
                             or f"episode {row['uuid'][:12]}"),
                "type": "event",
                "body": (
                    f"provenance: {SOURCE}\ngraphiti uuid: {row['uuid']}"
                    f"\nsource: {row.get('source', '')}"
                    f"\ncreated: {row.get('created_at', '')}\n\n{content}"
                ),
                "name": name,
                "provenance": [SOURCE],
            })
        for start in range(0, len(specs), BATCH):
            result = store.record_many(specs[start:start + BATCH])
            if result.rejected:
                raise ValueError(f"episodes rejected: {result.rejected[0].errors}")
        counts["episodes"] = len(specs)

    entities_path = export_dir / "entities.jsonl"
    if entities_path.exists():
        entity_specs: list[dict[str, object]] = []
        for line in entities_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            name = _slug("ent", row["uuid"])
            index[row["uuid"]] = name
            summary = (row.get("summary") or "").strip()
            entity_specs.append({
                "abstract": (" ".join(summary.split())[: store.config.storage.abstract_max_chars]
                             or f"entity {row.get('name') or row['uuid'][:12]}"),
                "type": "entity",
                "body": (
                    f"provenance: {SOURCE}\ngraphiti uuid: {row['uuid']}"
                    f"\nname: {row.get('name', '')}"
                    f"\ncreated: {row.get('created_at', '')}\n\n{summary}"
                ),
                "name": name,
                "provenance": [SOURCE],
            })
        for start in range(0, len(entity_specs), BATCH):
            result = store.record_many(entity_specs[start:start + BATCH])
            if result.rejected:
                raise ValueError(f"entities rejected: {result.rejected[0].errors}")
        counts["entities"] = len(entity_specs)

    edges_path = export_dir / "edges.jsonl"
    if edges_path.exists():
        claim_specs: list[dict[str, object]] = []
        edge_links: dict[str, list[str]] = {}
        for line in edges_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            src, dst = index.get(row["src"]), index.get(row["dst"])
            fact = (row.get("fact") or "").strip()
            if fact and row["rel"] == "RELATES_TO":
                claim_specs.append({
                    "abstract": " ".join(fact.split())[
                        : store.config.storage.abstract_max_chars
                    ] or "graphiti relation",
                    "type": "claim",
                    "standing": "accepted",  # live memory of record at cutover
                    "body": f"provenance: {SOURCE}\n\n{fact}",
                    "name": _slug("rel", _edge_key(row["id"])),
                    "provenance": [SOURCE],
                })
                continue
            if src and dst and src != dst:
                edge_links.setdefault(src, []).append(dst)
        for start in range(0, len(claim_specs), BATCH):
            result = store.record_many(claim_specs[start:start + BATCH])
            if result.rejected:
                raise ValueError(f"claims rejected: {result.rejected[0].errors}")
        counts["claims"] = len(claim_specs)
        for name, links in edge_links.items():
            record = store.find(name)
            if record is not None:
                record.links.extend(link for link in links if link not in record.links)
                store.write(record)
                counts["links"] += len(links)
    return counts
