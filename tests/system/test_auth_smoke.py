"""P13.4 auth blocker: prove credentials reach the sandbox spawn.

Live: exactly one model call through the production reasoner path.
"""

from __future__ import annotations

from mnemobun.adapters import doctor
from mnemobun.core.config import Config
from mnemobun.core.store import Store
from mnemobun.executor.agents import HARNESS_HERMES


def test_sandbox_spawn_has_auth(tmp_path):
    config = Config.default()
    config.executor.model = "mimo-v2.6-pro"
    store = Store(tmp_path / "store", config=config, agent="auth-smoke")
    store.init()
    report = doctor.smoke(store, host=HARNESS_HERMES)
    assert report["answered"], report
