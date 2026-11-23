"""The feed trigger: a cheap deterministic signal and the fire decision.

No LLM here on purpose. Per-turn features (user text vs tool noise, length,
novelty against the store, repetition in the local window) are scored as
messages arrive; the adapter computes the features, this module owns the
math and the policy. The signal is DERIVED from the unprocessed backlog at
read time — there is no separate accumulator to reset or lose on a crash.
"""

from __future__ import annotations

import dataclasses

from mnemobun.core.config import UsageConfig


@dataclasses.dataclass(frozen=True)
class TurnFeatures:
    """What the adapter knows about one raw turn. All cheap to compute."""

    is_user_text: bool
    characters: int
    novelty: float = 1.0  # 1 = nothing like it in the store, 0 = a repeat of it
    repetition: float = 0.0  # 1 = identical to recent turns, 0 = fresh


def score_turn(features: TurnFeatures, config: UsageConfig) -> float:
    """One turn's contribution to the feed signal."""
    base = (
        config.perception_user_text_weight
        if features.is_user_text
        else config.perception_tool_noise_weight
    )
    length = min(1.0, features.characters / config.perception_length_saturation_chars)
    novelty = config.perception_novelty_weight * max(0.0, min(1.0, features.novelty))
    penalty = config.perception_repetition_penalty * max(0.0, min(1.0, features.repetition))
    return max(0.0, base + length + novelty - penalty)


def backlog_signal(features: list[TurnFeatures], config: UsageConfig) -> float:
    """The unprocessed backlog's total signal, derived at read time."""
    return sum(score_turn(item, config) for item in features)


def should_feed(
    *,
    signal: float,
    quiet_seconds: float,
    backlog_tokens: float,
    backlog_turns: float,
    config: UsageConfig,
) -> bool:
    """Fire when the batch is worth it AND complete; never let a stream starve us.

    Force-fire on the token budget (MemGPT memory-pressure precedent) or the
    turn backstop — time and turn counts are backstops, not triggers.
    """
    if backlog_tokens >= config.token_budget:
        return True
    if backlog_turns >= config.backstop_turns:
        return True
    return signal >= config.signal_threshold and quiet_seconds >= config.quiet_seconds
