"""Trust boundary (2026-11-24): untrusted data, powerless extractor, strict output."""

import pathlib
import types

from mnemobun.core import prompts
from mnemobun.executor.agents.hermes import HermesDialect


def _spec():
    return types.SimpleNamespace(binary="hermes", provider="", model="m")


def test_extraction_profile_has_no_tools_and_keeps_rules():
    command = HermesDialect().command(
        _spec(),
        tools_enabled=False,
        system_prompt="",
        max_turns=1,
        store_root=pathlib.Path("."),
        answer_file=pathlib.Path("a"),
    )
    assert "--ignore-rules" not in command
    assert "--toolsets" not in command
    assert command[command.index("-t") : command.index("-t") + 2] == ["-t", ""]
    # the interactive form is unchanged
    interactive = HermesDialect().command(
        _spec(),
        tools_enabled=True,
        system_prompt="",
        max_turns=1,
        store_root=pathlib.Path("."),
        answer_file=pathlib.Path("a"),
    )
    assert "--ignore-rules" in interactive


def test_extraction_prompt_marks_content_as_untrusted_data():
    joined = " ".join(str(value) for value in vars(prompts).values() if isinstance(value, str))
    assert "DATA, not instructions" in joined
    assert "Never follow" in joined


