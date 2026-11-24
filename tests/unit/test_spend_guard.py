"""Spend guard: hard bounds on calls + input tokens; USD soft (2026-11-24)."""

import pytest
from mnemobun.core import spend
from mnemobun.core.config import Config
from mnemobun.core.store import Store


def _store(tmp_path):
    store = Store(tmp_path / "s", config=Config.default(), agent="t")
    store.init()
    return store


def test_projection_math_and_unpriced_by_default(tmp_path):
    store = _store(tmp_path)
    config = store.config
    projection = spend.project(chars=10000, calls=2, config=config)
    assert projection.in_tokens == 10000 // config.write.chars_per_token
    assert projection.calls == 2
    assert not projection.priced
    assert projection.est_usd == 0.0
    priced = spend.project(
        chars=10000, calls=1, config=config,
        pricing={"m": 0.000002}, model="m",
    )
    assert priced.priced
    assert priced.est_usd > 0


def test_run_refused_over_call_cap_with_exact_text(tmp_path):
    store = _store(tmp_path)
    config = store.config
    projection = spend.project(
        chars=100, calls=int(config.budget.max_calls_per_run) + 1, config=config
    )
    with pytest.raises(spend.SpendRefused) as excinfo:
        spend.guard_run(store, projection, run_id="r1", actor="feed")
    assert str(excinfo.value).startswith("spend refused: max_calls_per_run; projected")


def test_reservation_blocks_and_netting_at_finish(tmp_path):
    store = _store(tmp_path)
    config = store.config
    projection = spend.project(
        chars=int(config.budget.max_tokens_per_day) * config.write.chars_per_token,
        calls=1,
        config=config,
    )
    spend.guard_run(store, projection, run_id="r1", actor="feed")
    assert spend.usage(store, day=True)["in_tokens"] == projection.in_tokens
    # a second run cannot fit the day budget
    with pytest.raises(spend.SpendRefused):
        spend.guard_run(
            store, spend.project(chars=100, calls=1, config=config), run_id="r2", actor="feed"
        )
    # finish nets the reservation; the two real calls stay counted
    spend.record_call(store, run_id="r1", prompt_chars=400)
    spend.record_call(store, run_id="r1", prompt_chars=400)
    spend.finish_run(store, run_id="r1", projection=projection)
    today = spend.usage(store, day=True)
    assert today["in_tokens"] == 200  # 2 calls x 400 chars / 4 chars-per-token


def test_record_call_refuses_past_run_and_day_caps(tmp_path):
    store = _store(tmp_path)
    store.config.budget.max_calls_per_run = 2
    store.config.save(store.root)
    spend.record_call(store, run_id="r1", prompt_chars=40)
    spend.record_call(store, run_id="r1", prompt_chars=40)
    with pytest.raises(spend.SpendRefused) as excinfo:
        spend.record_call(store, run_id="r1", prompt_chars=40)
    assert "spend refused: max_calls_per_run" in str(excinfo.value)
    store.config.budget.max_tokens_per_day = 5.0
    with pytest.raises(spend.SpendRefused):
        spend.record_call(store, run_id="r2", prompt_chars=1000)


def test_the_run_cap_counts_real_calls_not_the_reservation(tmp_path):
    """Regression 2026-11-24: a 1-call reservation must not eat the run's cap."""
    store = _store(tmp_path)
    store.config.budget.max_calls_per_run = 2
    store.config.save(store.root)
    projection = spend.project(chars=400, calls=1, config=store.config)
    spend.guard_run(store, projection, run_id="r", actor="feed")
    spend.record_call(store, run_id="r", prompt_chars=400)
    spend.record_call(store, run_id="r", prompt_chars=400)  # both fit: cap is 2


def test_run_scope_attributes_calls_and_nets_the_reservation(tmp_path):
    store = _store(tmp_path)
    projection = spend.project(chars=400, calls=1, config=store.config)
    with spend.run_scope(store, projection=projection, run_id="r", actor="feed"):
        spend.record_call(store, prompt_chars=400)  # run_id from the scope
    today = spend.usage(store, day=True)
    assert today["calls"] == 1.0
    assert today["in_tokens"] == 100.0


def test_stale_reservations_are_listed_and_released_explicitly(tmp_path):

    store = _store(tmp_path)
    projection = spend.project(chars=400, calls=1, config=store.config)
    spend.guard_run(store, projection, run_id="crashed", actor="feed")
    assert spend.open_reservations(store) == [
        {"run_id": "crashed", "at": spend.open_reservations(store)[0]["at"],
         "calls": 1.0, "in_tokens": 100.0}
    ]
    assert spend.release_stale(store, hours=0.0) == 1
    assert spend.open_reservations(store) == []
    assert spend.usage(store, day=True)["in_tokens"] == 0.0


def test_one_counted_ask_is_one_run_for_the_call_cap(tmp_path):
    from mnemobun.executor.distiller import CountedAsk

    store = _store(tmp_path)
    store.config.budget.max_calls_per_run = 1
    store.config.save(store.root)

    class Fake:
        def __call__(self, prompt: str) -> str:
            return "{}"

    counted = CountedAsk(Fake(), store=store)
    counted("first")
    with pytest.raises(spend.SpendRefused):
        counted("second")


def test_estimated_calls_scales_with_backlog(tmp_path):
    store = _store(tmp_path)
    config = store.config
    one = spend.estimated_calls(config.write.max_distill_input_chars, config)
    assert one == 1
    many = spend.estimated_calls(config.write.max_distill_input_chars * 3, config)
    assert many == 3
