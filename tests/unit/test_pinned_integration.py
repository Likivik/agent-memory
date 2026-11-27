"""P9: the rendered block survives the trip through a harness channel, and old stores stay quiet."""

from __future__ import annotations

from mnemobun.adapters import channels
from mnemobun.core import pinned


def test_rendered_block_survives_the_channel_round_trip(store, tmp_path):
    store.record(name="rule-one", abstract="never prune without approval", type="claim")
    pinned.set_pinned(store, "rule-one", pinned=True)
    block = pinned.render(store)
    target = tmp_path / "AGENTS.md"
    target.write_text("# project rules\n")

    delivery = channels.place(channels.for_harness("codex"), block, target=target)

    text = target.read_text()
    assert block in text
    assert text.startswith("# project rules")
    assert delivery.digest == pinned.block(store).digest


def test_store_without_pinned_fields_reads_clean(store):
    store.record(name="legacy-claim", abstract="a claim from before pinning", type="claim")

    assert pinned.render(store) == ""


def test_hermes_channel_is_the_provider_surface():
    channel = channels.for_harness("hermes")

    assert channel.surface == channels.SURFACE_SYSTEM_BLOCK
    assert channel.preserved is True
    assert channel.refresh == channels.REFRESH_PER_TURN
