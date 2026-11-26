"""P9: the rendered block survives the trip through a host channel, and old stores stay quiet."""

from __future__ import annotations

from mnemobun.adapters import pin_channel
from mnemobun.core import pinned


def test_rendered_block_survives_the_channel_round_trip(store, tmp_path):
    store.record(name="rule-one", abstract="never prune without approval", type="claim")
    pinned.set_pinned(store, "rule-one", pinned=True)
    block = pinned.render(store)
    target = tmp_path / "AGENTS.md"
    target.write_text("# project rules\n")

    delivery = pin_channel.deliver(pin_channel.channel("codex"), block, target=target)

    text = target.read_text()
    assert block in text
    assert text.startswith("# project rules")
    assert delivery.digest == pinned.block(store).digest


def test_store_without_pinned_fields_reads_clean(store):
    store.record(name="legacy-claim", abstract="a claim from before pinning", type="claim")

    assert pinned.render(store) == ""


def test_hermes_channel_is_the_provider_surface():
    host = pin_channel.channel("hermes")

    assert host.surface == pin_channel.SURFACE_SYSTEM_BLOCK
    assert host.preserved is True
    assert host.refresh == pin_channel.REFRESH_PER_TURN
