"""P5: every harness receives the same bytes, through its own surface."""

from __future__ import annotations

import pytest
from mnemobun.adapters import channels
from mnemobun.adapters.channels import (
    MARKER_END,
    MARKER_START,
    Channel,
    place,
    splice,
)

BLOCK = "- never prune containers without approval (rule-one, 2026-11-25)"


def test_every_channel_renders_the_same_digest(tmp_path):
    digests = {
        place(channels.for_harness(harness), BLOCK, state_dir=tmp_path).digest
        for harness in ("hermes", "codex", "codex", "muse")
    }

    assert len(digests) == 1
    assert digests == {channels.digest_of(BLOCK)}


def test_file_channel_replaces_only_its_region(tmp_path):
    target = tmp_path / "AGENTS.md"
    target.write_text("# House rules\nkeep me\n")

    place(channels.for_harness("codex"), BLOCK, target=target)
    place(channels.for_harness("codex"), "- changed rule", target=target)

    text = target.read_text()
    assert text.startswith("# House rules\nkeep me\n")
    assert "changed rule" in text
    assert BLOCK not in text
    assert text.count(MARKER_START) == 1 and text.count(MARKER_END) == 1


def test_unchanged_block_is_not_rewritten(tmp_path):
    target = tmp_path / "AGENTS.md"
    place(channels.for_harness("codex"), BLOCK, target=target)
    first = target.stat().st_mtime_ns

    result = place(channels.for_harness("codex"), BLOCK, target=target)

    assert result.wrote is False
    assert target.stat().st_mtime_ns == first


def test_degraded_channel_is_flagged():
    assert channels.for_harness("muse").degraded is True
    assert channels.for_harness("hermes").degraded is False


def test_channel_records_the_digest_it_delivered(tmp_path):
    place(channels.for_harness("hermes"), BLOCK, state_dir=tmp_path)

    assert channels.recorded(tmp_path)["hermes"] == channels.digest_of(BLOCK)


def test_a_new_harness_needs_no_renderer_change(tmp_path):
    channels.CHANNELS["dummy"] = Channel(
        harness="dummy", surface="system_block", preserved=True, refresh="per_run", max_bytes=1024
    )
    try:
        assert place(channels.for_harness("dummy"), BLOCK).digest == channels.digest_of(BLOCK)
    finally:
        del channels.CHANNELS["dummy"]


def test_splice_appends_when_no_region_exists():
    assert MARKER_START in splice("", BLOCK)


def test_oversized_block_is_refused(tmp_path):
    small = Channel(harness="tiny", surface="system_block", preserved=True, refresh="per_run",
                       max_bytes=10)

    with pytest.raises(ValueError):
        place(small, BLOCK)


def test_unknown_channel_names_itself():
    with pytest.raises(KeyError, match="no channel registered for harness"):
        channels.for_harness("nope")


def test_muse_prompt_file_is_not_clobbered(tmp_path):
    target = tmp_path / "prompt.md"
    target.write_text("# my prompt\nimportant instruction\n")

    place(channels.for_harness("muse"), BLOCK, target=target)

    text = target.read_text()
    assert text.startswith("# my prompt")
    assert "important instruction" in text
    assert BLOCK.split(" (")[0] in text


def test_reversed_markers_do_not_corrupt_the_file(tmp_path):
    target = tmp_path / "AGENTS.md"
    target.write_text(f"{MARKER_END}\noops\n{MARKER_START}\n")

    place(channels.for_harness("codex"), BLOCK, target=target)

    text = target.read_text()
    assert "oops" in text
    assert text.count(BLOCK) == 1


def test_deliver_writes_the_block_into_a_harness_file(store, tmp_path):
    from mnemobun.core import pinned

    store.record(name="rule-one", abstract="never prune without approval", type="claim")
    pinned.set_pinned(store, "rule-one", pinned=True)
    target = tmp_path / "AGENTS.md"
    target.write_text("# project\n")

    delivery = channels.deliver(store, "codex", target)

    assert delivery.wrote is True
    assert "never prune without approval" in target.read_text()
    assert target.read_text().startswith("# project")


def test_executor_block_is_empty_for_hermes(store):
    from mnemobun.core import pinned

    store.record(name="rule-one", abstract="never prune without approval", type="claim")
    pinned.set_pinned(store, "rule-one", pinned=True)

    assert channels.executor_block(store, "hermes") == ""


def test_executor_block_carries_the_rule_for_headless_hosts(store):
    from mnemobun.core import pinned

    store.record(name="rule-one", abstract="never prune without approval", type="claim")
    pinned.set_pinned(store, "rule-one", pinned=True)

    for harness in ("codex", "codex", "muse-code"):
        block = channels.executor_block(store, harness)
        assert "never prune without approval" in block


def test_executor_block_survives_an_unknown_host(store):
    assert channels.executor_block(store, "some-future-harness") == ""
