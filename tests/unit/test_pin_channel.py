"""P5: every host receives the same bytes, through its own surface."""

from __future__ import annotations

import pytest
from mnemobun.adapters import pin_channel
from mnemobun.adapters.pin_channel import (
    MARKER_END,
    MARKER_START,
    PinChannel,
    deliver,
    splice,
)

BLOCK = "- never prune containers without approval (rule-one, 2026-11-25)"


def test_every_channel_renders_the_same_digest(tmp_path):
    digests = {
        deliver(pin_channel.channel(host), BLOCK, state_dir=tmp_path).digest
        for host in ("hermes", "claude-code", "codex", "muse")
    }

    assert len(digests) == 1
    assert digests == {pin_channel.digest_of(BLOCK)}


def test_file_channel_replaces_only_its_region(tmp_path):
    target = tmp_path / "CLAUDE.md"
    target.write_text("# House rules\nkeep me\n")

    deliver(pin_channel.channel("claude-code"), BLOCK, target=target)
    deliver(pin_channel.channel("claude-code"), "- changed rule", target=target)

    text = target.read_text()
    assert text.startswith("# House rules\nkeep me\n")
    assert "changed rule" in text
    assert BLOCK not in text
    assert text.count(MARKER_START) == 1 and text.count(MARKER_END) == 1


def test_unchanged_block_is_not_rewritten(tmp_path):
    target = tmp_path / "CLAUDE.md"
    deliver(pin_channel.channel("claude-code"), BLOCK, target=target)
    first = target.stat().st_mtime_ns

    result = deliver(pin_channel.channel("claude-code"), BLOCK, target=target)

    assert result.wrote is False
    assert target.stat().st_mtime_ns == first


def test_degraded_channel_is_flagged():
    assert pin_channel.channel("muse").degraded is True
    assert pin_channel.channel("hermes").degraded is False


def test_channel_records_the_digest_it_delivered(tmp_path):
    deliver(pin_channel.channel("hermes"), BLOCK, state_dir=tmp_path)

    assert pin_channel.recorded(tmp_path)["hermes"] == pin_channel.digest_of(BLOCK)


def test_new_host_needs_no_renderer_change(tmp_path):
    pin_channel.REGISTRY["dummy"] = PinChannel(
        host="dummy", surface="system_block", preserved=True, refresh="per_run", max_bytes=1024
    )
    try:
        assert deliver(pin_channel.channel("dummy"), BLOCK).digest == pin_channel.digest_of(BLOCK)
    finally:
        del pin_channel.REGISTRY["dummy"]


def test_splice_appends_when_no_region_exists():
    assert MARKER_START in splice("", BLOCK)


def test_oversized_block_is_refused(tmp_path):
    small = PinChannel(host="tiny", surface="system_block", preserved=True, refresh="per_run",
                       max_bytes=10)

    with pytest.raises(ValueError):
        deliver(small, BLOCK)


def test_unknown_channel_names_itself():
    with pytest.raises(KeyError, match="unknown pin channel"):
        pin_channel.channel("nope")


def test_muse_prompt_file_is_not_clobbered(tmp_path):
    target = tmp_path / "prompt.md"
    target.write_text("# my prompt\nimportant instruction\n")

    deliver(pin_channel.channel("muse"), BLOCK, target=target)

    text = target.read_text()
    assert text.startswith("# my prompt")
    assert "important instruction" in text
    assert BLOCK.split(" (")[0] in text


def test_reversed_markers_do_not_corrupt_the_file(tmp_path):
    target = tmp_path / "CLAUDE.md"
    target.write_text(f"{MARKER_END}\noops\n{MARKER_START}\n")

    deliver(pin_channel.channel("claude-code"), BLOCK, target=target)

    text = target.read_text()
    assert "oops" in text
    assert text.count(BLOCK) == 1


def test_sync_writes_the_block_into_a_host_file(store, tmp_path):
    from mnemobun.core import pinned

    store.record(name="rule-one", abstract="never prune without approval", type="claim")
    pinned.set_pinned(store, "rule-one", pinned=True)
    target = tmp_path / "AGENTS.md"
    target.write_text("# project\n")

    delivery = pin_channel.sync(store, "codex", target)

    assert delivery.wrote is True
    assert "never prune without approval" in target.read_text()
    assert target.read_text().startswith("# project")


def test_executor_block_is_empty_for_hermes(store):
    from mnemobun.core import pinned

    store.record(name="rule-one", abstract="never prune without approval", type="claim")
    pinned.set_pinned(store, "rule-one", pinned=True)

    assert pin_channel.executor_block(store, "hermes") == ""


def test_executor_block_carries_the_rule_for_headless_hosts(store):
    from mnemobun.core import pinned

    store.record(name="rule-one", abstract="never prune without approval", type="claim")
    pinned.set_pinned(store, "rule-one", pinned=True)

    for host in ("claude-code", "codex", "muse-code"):
        block = pin_channel.executor_block(store, host)
        assert "never prune without approval" in block


def test_executor_block_survives_an_unknown_host(store):
    assert pin_channel.executor_block(store, "some-future-host") == ""
