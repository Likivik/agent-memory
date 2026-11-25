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
