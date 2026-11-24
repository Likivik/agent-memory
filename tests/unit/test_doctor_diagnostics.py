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


def test_the_reasoner_check_names_an_explicit_endpoint(tmp_path):
    store = _store(tmp_path)
    store.config.executor.model = "gemini-test"
    store.config.executor.endpoint = "https://models.example/v1"

    checks = doctor._reasoner_checks(store, "", {"GEMINI_API_KEY": "user-key"})

    assert "explicit model endpoint" in _details(checks)
    assert all(check.ok for check in checks)


def test_the_reasoner_check_refuses_a_non_endpoint_reasoner(tmp_path):
    store = _store(tmp_path)
    store.config.executor.reasoner = "host"
    store.config.executor.model = "m"

    checks = doctor._reasoner_checks(store, "", {})

    assert any(not check.ok for check in checks)
    assert "unsupported reasoner" in _details(checks)


def test_the_reasoner_check_reports_missing_credentials(tmp_path):
    store = _store(tmp_path)

    checks = doctor._reasoner_checks(store, "", {})

    assert any(not check.ok for check in checks)
    assert "requires a user-owned endpoint and API key" in _details(checks)


def test_the_reasoner_check_honors_the_configured_key_env(tmp_path):
    store = _store(tmp_path)
    store.config.executor.endpoint = "https://models.example/v1"
    store.config.executor.key_env = "MY_OWN_KEY"

    checks = doctor._reasoner_checks(store, "", {"MY_OWN_KEY": "user-key"})

    assert all(check.ok for check in checks)


def test_the_reasoner_check_accepts_a_vertex_project(tmp_path):
    store = _store(tmp_path)

    checks = doctor._reasoner_checks(
        store, "", {"GOOGLE_CLOUD_PROJECT": "user-project"}
    )

    assert all(check.ok for check in checks)
    assert "Vertex AI project user-project" in _details(checks)


def test_store_checks_confirm_the_store_is_initialized_and_writable(tmp_path):
    store = _store(tmp_path)

    checks = doctor._store_checks(store)

    codes = {check.code for check in checks}
    assert "STORE_INITIALIZED" in codes
    assert all(check.ok for check in checks)


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
    assert "no model configured" in str(report["reason"])
