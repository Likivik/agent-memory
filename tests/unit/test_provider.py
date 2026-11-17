"""P3+P4 acceptance: the Hermes provider and the memory_stats tool."""

from __future__ import annotations

from agent_memory.adapters import moments
from agent_memory.core import standing
from agent_memory.core.record import STANDING_ACCEPTED, STANDING_PROPOSED
from agent_memory.executor.hermes_provider import HermesMemoryProvider
from agent_memory.mcp.tools import TOOL_STATS, dispatch


def _provider(store):
    return HermesMemoryProvider(store=store)


def _claim(store, name, abstract):
    claim = store.record(abstract=abstract, type="claim", body=abstract, name=name)
    standing.set_standing(store, name, STANDING_ACCEPTED, cause="user_confirm")
    return claim


def test_prefetch_respects_byte_budget_and_top_k(store):
    for index in range(12):
        _claim(store, f"claim-{index}", f"Claim number {index} about deploying things")
    provider = _provider(store)
    block = provider.prefetch("")
    lines = [line for line in block.splitlines() if line.startswith("- ")]
    assert len(lines) <= store.config.provider.prefetch_top_k
    assert len(block.encode("utf-8")) <= store.config.provider.prefetch_budget_bytes
    assert block  # the floor is filled


def test_prefetch_with_query_prefers_recall_hits(store):
    _claim(store, "backup-schedule", "Backups run weekly btrfs snapshots")
    _claim(store, "unrelated", "Something about sailboats")
    provider = _provider(store)
    block = provider.prefetch("btrfs backups")
    assert "backup-schedule" in block


def test_sync_turn_records_events_and_never_claims(store):
    provider = _provider(store)
    provider.sync_turn("what backs up /var?", "weekly btrfs snapshots", session_id="s1")
    provider.sync_turn("   ", "   ", session_id="s1")  # blank turn: no write
    records = {record.name: record for record in store.records(include_invalid=True)}
    events = [record for record in records.values() if record.type == "event"]
    assert len(events) == 1
    assert any("provenance" in str(ref) or ref for ref in events[0].provenance)
    assert not any(record.type == "claim" for record in records.values())


def test_provider_never_auto_accepts_claims(store):
    provider = _provider(store)
    provider.sync_turn("we ship tuesdays", "noted", session_id="s1")
    # The agent writes the claim explicitly; it must land as `proposed`.
    claim = store.record(
        abstract="We ship on Tuesdays", type="claim", body="We ship on Tuesdays",
        name="ship-tuesdays",
    )
    assert claim.standing == STANDING_PROPOSED
    provider.sync_turn("again", "ok", session_id="s2")
    assert store.find(claim.name).standing == STANDING_PROPOSED


def test_verify_without_reasoner_abstains_and_with_reasoner_labels(store):
    _claim(store, "backup-schedule", "Backups run weekly btrfs snapshots")
    provider = _provider(store)
    abstained = provider.verify("Backups run weekly", "backup schedule")
    assert abstained["label"] == "abstain"
    provider.reasoner = lambda prompt: "supported"
    labelled = provider.verify("Backups run weekly", "backup schedule")
    assert labelled["label"] == "supported"


def test_stats_tool_reports_counts_and_index(store):
    _claim(store, "backup-schedule", "Backups run weekly btrfs snapshots")
    store.record(abstract="A plain preference", type="preference", body="x", name="pref")
    result = dispatch(store, TOOL_STATS, {})
    assert result["by_type"]["claim"] == 1
    assert result["by_type"]["preference"] == 1
    assert result["by_standing"][STANDING_ACCEPTED] == 2  # claim + legacy preference
    assert result["index_bytes"] > 0
    assert result["last_sync"]


def test_run_sleep_not_due_skips(store):
    provider = _provider(store)
    provider.sync_turn("one", "one", session_id="s1")  # 1 session < trigger_min_sessions
    result = provider.run_sleep(1)
    assert result == {"skipped": "not due"}


def test_run_sleep_accepts_only_via_menu_with_stub_reasoner(store, clock, tmp_path, config):
    config.manage.trigger_min_sessions = 1
    second = type(store)(tmp_path / "sleep", config=config, clock=clock, agent="t")
    second.init()
    second.record(abstract="A thing worth keeping", type="fact", body="x", name="keep-me")
    second.record(abstract="A thing worth keeping", type="fact", body="x", name="keep-me-2")
    provider = _provider(second)
    provider.reasoner = lambda prompt: "no rulings"  # rambles: nothing is decided
    result = provider.run_sleep(5)
    assert "skipped" not in result
    # The deterministic half ran; proposals that need a real ruling stay open.
    assert second.find("keep-me") is not None


def test_hermes_moments_mapping():
    assert moments.moment_for("hermes", "SessionStart") == moments.MOMENT_INJECT
    assert moments.moment_for("hermes", "PreCompact") == moments.MOMENT_EVICT
    assert moments.moment_for("hermes", "Stop") == moments.MOMENT_PAUSE
    assert "hermes" in moments.hosts()
