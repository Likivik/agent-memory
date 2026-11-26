"""P13.4 auth blocker: prove credentials reach the sandbox spawn.

Live: exactly one model call through the production reasoner path.
"""

from __future__ import annotations

import os

import pytest
from mnemobun.adapters import doctor
from mnemobun.core.config import Config
from mnemobun.core.store import Store
from mnemobun.executor.drivers import HARNESS_HERMES

live = pytest.mark.skipif(
    os.environ.get("MNEMOBUN_LIVE") != "1",
    reason="one real model call: set MNEMOBUN_LIVE=1 to run it",
)


@live
def test_sandbox_spawn_has_auth(tmp_path):
    config = Config.default()
    config.executor.model = "mimo-v2.6-pro"
    store = Store(tmp_path / "store", config=config, writer="auth-smoke")
    store.init()
    report = doctor.smoke(store, harness=HARNESS_HERMES)
    assert report["answered"], report
