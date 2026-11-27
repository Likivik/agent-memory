"""CLI-level crontab install/status/remove without touching the user's real crontab."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest
from mnemobun.adapters import capture, cron_schedule
from mnemobun.cli.main import EXIT_OK, main
from mnemobun.core import dreaming
from mnemobun.core.store import Store
from mnemobun.core.watermark import Watermark

POSIX_CRON = pytest.mark.skipif(os.name == "nt", reason="cron scheduling is POSIX-only")

FAKE_CRONTAB = """#!/bin/sh
set -eu
if [ "$1" = "-l" ]; then
  if [ -f "$FAKE_CRONTAB_FILE" ]; then
    cat "$FAKE_CRONTAB_FILE"
    exit 0
  fi
  echo "no crontab for test" >&2
  exit 1
fi
if [ "$1" = "-" ]; then
  cat > "$FAKE_CRONTAB_FILE"
  exit 0
fi
exit 2
"""


@POSIX_CRON
def test_cli_manages_one_store_block_and_preserves_unrelated_jobs(tmp_path, monkeypatch, capsys):
    store = tmp_path / "Store With Spaces"
    crontab_file = tmp_path / "user.crontab"
    crontab_file.write_text("11 2 * * * /usr/bin/unrelated\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    crontab = bin_dir / "crontab"
    crontab.write_text(FAKE_CRONTAB, encoding="utf-8")
    crontab.chmod(0o755)
    mem = bin_dir / "mnemobun"
    mem.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    mem.chmod(0o755)
    environment = tmp_path / "reasoner.env"
    environment.write_text("HTTPS_PROXY=https://example.test\n", encoding="utf-8")
    environment.chmod(0o600)
    monkeypatch.setenv("FAKE_CRONTAB_FILE", str(crontab_file))
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    monkeypatch.setattr(
        "mnemobun.adapters.cron_schedule._scheduler_running", lambda: True
    )
    monkeypatch.setattr("mnemobun.adapters.cron_schedule._is_wsl", lambda: False)

    def run(*args):
        assert main(["--store", str(store), "--json", "cron", *args]) == EXIT_OK
        return json.loads(capsys.readouterr().out)

    assert main(["--store", str(store), "--json", "init"]) == EXIT_OK
    capsys.readouterr()
    installed = run(
        "install",
        "--interval-minutes",
        "15",
        "--mem-path",
        str(mem),
        "--env-file",
        str(environment),
    )
    unchanged = run(
        "install",
        "--interval-minutes",
        "15",
        "--mem-path",
        str(mem),
        "--env-file",
        str(environment),
    )
    current = run("status")
    removed = run("remove")

    assert installed["status"] == "installed"
    assert unchanged["status"] == "unchanged"
    assert current["installed"] is True
    assert current["entry"].startswith("*/15 * * * * ")
    assert "--json sleep --if-due --trigger-source cron" in current["entry"]
    assert str(environment) in current["entry"]
    assert removed["status"] == "removed"
    assert crontab_file.read_text("utf-8") == "11 2 * * * /usr/bin/unrelated\n"


@POSIX_CRON
def test_generated_cron_command_completes_a_dream_in_an_independent_process(
    tmp_path, monkeypatch
):
    """The installed command runs in its own process and finishes a dream with no reasoner."""
    store = Store(tmp_path / "Store With Spaces")
    store.config.manage.trigger_min_sessions = 1
    store.config.manage.git_commit = False
    store.init()
    store.record(
        type="fact",
        fields={"subject": "cron acceptance"},
        abstract="Nobody asks about this",
        usage=store.config.usage.floor,
    )
    capture.capture(
        store,
        "settled-session",
        ["user: remember cron acceptance", "assistant: noted"],
        source="pause",
    )
    mark = Watermark(store.layout).read("settled-session")
    Watermark(store.layout).settle("settled-session", mark.consumed)

    log = tmp_path / "cron.log"
    crontab = {"text": ""}
    monkeypatch.setattr(cron_schedule, "_require_crontab", lambda: "/usr/bin/crontab")
    monkeypatch.setattr(cron_schedule, "_read_crontab", lambda _binary: crontab["text"])
    monkeypatch.setattr(
        cron_schedule,
        "_write_crontab",
        lambda _binary, content: crontab.__setitem__("text", content),
    )
    monkeypatch.setattr(cron_schedule, "_scheduler_running", lambda: True)
    monkeypatch.setattr(cron_schedule, "_is_wsl", lambda: False)

    mem = pathlib.Path(sys.executable).parent / "mnemobun"
    installed = cron_schedule.install(store, mem_path=str(mem), log_path=str(log))
    completed = subprocess.run(
        str(installed["command"]),
        shell=True,
        executable="/bin/sh",
        check=False,
    )

    assert completed.returncode == 0
    output = json.loads(log.read_text("utf-8"))
    assert output["slept"] is True
    assert output["status"] == "succeeded"
    assert output["trigger_source"] == "cron"
    assert output["decisions"] == []
    assert pathlib.Path(output["path"]).is_file()
    state = dreaming.state(Store(store.root))
    assert state["status"] == dreaming.STATUS_SUCCEEDED
    assert state["last_report"] == output["path"]
