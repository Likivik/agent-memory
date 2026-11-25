"""Doctor speaks to users when the system is broken - pin what it says."""

from __future__ import annotations

from mnemobun.adapters import doctor
from mnemobun.core.config import Config
from mnemobun.core.store import Store


def _store(tmp_path):
    store = Store(tmp_path / "store", config=Config.default(), agent="doctor-test")
    store.init()
    return store


def _details(checks) -> str:
    return " | ".join(f"{check.code}: {check.detail}" for check in checks)


def test_the_reasoner_check_names_the_host(tmp_path):
    store = _store(tmp_path)

    checks = doctor._reasoner_checks(store, "", {})

    assert all(check.ok for check in checks)
    assert "claude-code CLI" in _details(checks)


def test_the_reasoner_check_refuses_a_non_host_reasoner(tmp_path):
    store = _store(tmp_path)
    store.config.executor.reasoner = "endpoint"

    checks = doctor._reasoner_checks(store, "", {})

    assert any(not check.ok for check in checks)
    assert "unsupported reasoner" in _details(checks)


def test_store_checks_confirm_the_store_is_initialized_and_writable(tmp_path):
    store = _store(tmp_path)

    checks = doctor._store_checks(store)

    codes = {check.code for check in checks}
    assert "STORE_INITIALIZED" in codes
    assert all(check.ok for check in checks if check.required)
    assert {"CAPTURE_HEALTHY", "ROUTE_UNSET"} <= codes  # advisory, not required


def test_smoke_reports_success_with_a_working_reasoner(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(
        "mnemobun.executor.distiller.distiller",
        lambda _config, **_kw: lambda _prompt: "OK",
    )

    report = doctor.smoke(store, model="m")

    assert report["answered"] is True
    assert report["answer"] == "OK"


def test_smoke_reports_failure_instead_of_raising_when_unconfigured(tmp_path):
    store = _store(tmp_path)

    report = doctor.smoke(store)

    assert report["answered"] is False


def test_pinned_block_over_budget_is_reported(tmp_path):
    from mnemobun.core import pinned

    store = _store(tmp_path)
    store.config.recall.pinned_max_bytes = 60
    store.record(name="rule-one", abstract="a rule long enough to overflow the pinned block",
                 type="claim")
    pinned.set_pinned(store, "rule-one", pinned=True)

    codes = {check.code for check in doctor._store_checks(store)}

    assert "PINNED_OVER_BUDGET" in codes


def test_stale_pin_is_reported(tmp_path):
    from mnemobun.core import pinned
    from mnemobun.core.standing import set_standing

    store = _store(tmp_path)
    store.record(name="rule-one", abstract="always ask first", type="claim")
    pinned.set_pinned(store, "rule-one", pinned=True)
    set_standing(store, "rule-one", "contested", cause="test", force=True)

    codes = {check.code for check in doctor._store_checks(store)}

    assert "PINNED_STALE" in codes


def test_unreadable_pinned_roster_is_reported(tmp_path):
    store = _store(tmp_path)
    (store.layout.state_dir / "pins.json").write_text("{not json")

    codes = {check.code for check in doctor._store_checks(store)}

    assert "PINNED_UNREADABLE" in codes
