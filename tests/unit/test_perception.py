"""Feed trigger policy: signal math and the fire decision."""

from mnemobun.core.config import Config
from mnemobun.core.perception import TurnFeatures, backlog_signal, should_feed


def _config():
    return Config.default().usage


def test_user_text_scores_above_tool_noise():
    config = _config()
    user = TurnFeatures(is_user_text=True, characters=100)
    tool = TurnFeatures(is_user_text=False, characters=100)
    from mnemobun.core.perception import score_turn

    assert user.novelty == 1.0

    assert score_turn(user, config) > score_turn(tool, config)


def test_signal_saturates_with_length_and_falls_with_repetition():
    config = _config()
    from mnemobun.core.perception import score_turn

    short = score_turn(TurnFeatures(True, 10), config)
    long = score_turn(TurnFeatures(True, 100000), config)
    assert long > short
    repeated = score_turn(TurnFeatures(True, 100, novelty=0.0, repetition=1.0), config)
    fresh = score_turn(TurnFeatures(True, 100), config)
    assert repeated < fresh


def test_trigger_needs_signal_and_quiet():
    config = _config()
    kwargs = {"backlog_tokens": 0.0, "backlog_turns": 0.0, "config": config}
    assert not should_feed(signal=0.0, quiet_seconds=99999.0, **kwargs)
    assert not should_feed(signal=999.0, quiet_seconds=0.0, **kwargs)
    assert should_feed(signal=config.signal_threshold, quiet_seconds=config.quiet_seconds, **kwargs)


def test_force_fire_on_budget_or_backstop_even_when_busy():
    config = _config()
    assert should_feed(
        signal=0.0, quiet_seconds=0.0, backlog_tokens=config.token_budget,
        backlog_turns=0.0, config=config,
    )
    assert should_feed(
        signal=0.0, quiet_seconds=0.0, backlog_tokens=0.0,
        backlog_turns=config.backstop_turns, config=config,
    )


def test_backlog_signal_is_the_sum():
    config = _config()
    items = [TurnFeatures(True, 100), TurnFeatures(True, 100)]
    from mnemobun.core.perception import score_turn

    assert backlog_signal(items, config) == sum(score_turn(i, config) for i in items)
