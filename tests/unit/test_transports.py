"""A harness is a transport, not a branch. Adding one must not touch the driver."""

import pytest
from mnemobun.executor import drivers


def _spec(name):
    return drivers.DriverSpec(name=name, binary=name, model="a-model")


@pytest.mark.parametrize("name", drivers.TRANSPORTS)
def test_every_transport_builds_a_command_that_starts_with_its_binary(name, tmp_path):
    transport = drivers.TRANSPORTS[name]
    command = transport.command(
        _spec(name),
        tools_enabled=True,
        system_prompt="be a memory keeper",
        max_turns=10,
        store_root=tmp_path / "store",
        answer_file=tmp_path / "answer.txt",
    )
    assert command[0] == name
    assert "a-model" in command


@pytest.mark.parametrize("name", drivers.TRANSPORTS)
def test_the_system_prompt_reaches_the_harness_one_way_or_the_other(name, tmp_path):
    transport = drivers.TRANSPORTS[name]
    system = "you are a memory keeper"
    command = transport.command(
        _spec(name),
        tools_enabled=True,
        system_prompt=system,
        max_turns=10,
        store_root=tmp_path / "store",
        answer_file=tmp_path / "answer.txt",
    )
    delivered = transport.stdin("the question", system)
    assert system in " ".join(command) or system in (delivered or "")


@pytest.mark.parametrize("name", drivers.TRANSPORTS)
def test_no_transport_leaves_its_own_memory_layer_running(name, tmp_path):
    """Two memory systems in one run make the score unattributable."""
    transport = drivers.TRANSPORTS[name]
    command = " ".join(
        transport.command(
            _spec(name),
            tools_enabled=True,
            system_prompt="s",
            max_turns=10,
            store_root=tmp_path / "store",
            answer_file=tmp_path / "answer.txt",
        )
    )
    assert transport.disables_native_memory(command)






def test_codex_is_given_write_access_to_the_store_it_must_reach(tmp_path):
    store = tmp_path / "store"
    command = drivers.TRANSPORTS[drivers.HARNESS_CODEX].command(
        _spec(drivers.HARNESS_CODEX),
        tools_enabled=True,
        system_prompt="keeper",
        max_turns=7,
        store_root=store,
        answer_file=tmp_path / "answer.txt",
    )
    assert "--add-dir" in command
    assert str(store) in command
    assert "workspace-write" in command


def test_codex_without_tools_stays_read_only(tmp_path):
    command = drivers.TRANSPORTS[drivers.HARNESS_CODEX].command(
        _spec(drivers.HARNESS_CODEX),
        tools_enabled=False,
        system_prompt="",
        max_turns=7,
        store_root=None,
        answer_file=tmp_path / "answer.txt",
    )
    assert "read-only" in command
    assert "--add-dir" not in command


def test_hermes_enables_only_the_toolset_that_reaches_the_mem_cli(tmp_path):
    command = drivers.TRANSPORTS[drivers.HARNESS_HERMES].command(
        _spec(drivers.HARNESS_HERMES),
        tools_enabled=True,
        system_prompt="keeper",
        max_turns=7,
        store_root=tmp_path / "store",
        answer_file=tmp_path / "answer.txt",
    )
    toolsets = command[command.index("-t") + 1].split(",")
    assert "terminal" in toolsets
    assert "memory" not in toolsets


def test_codex_reads_its_answer_from_the_file_not_the_transcript(tmp_path):
    answer_file = tmp_path / "answer.txt"
    answer_file.write_text("the final answer\n", encoding="utf-8")
    noisy = (
        "sandbox: read-only\nsession id: abc\nuser\nquestion\ncodex\nthe final answer\ntokens used"
    )
    transport = drivers.TRANSPORTS[drivers.HARNESS_CODEX]
    assert transport.answer(noisy, answer_file) == "the final answer"




def test_an_unavailable_harness_is_reported_rather_than_silently_skipped():
    spec = drivers.DriverSpec(name="nope", binary="definitely-not-installed", model="m")
    assert not spec.available()


def test_hermes_re_adds_the_prefix_it_is_about_to_strip(tmp_path):
    """It consumes one provider prefix as routing; a publisher-qualified backend needs it back."""
    spec = drivers.DriverSpec(
        name=drivers.HARNESS_HERMES,
        binary="hermes",
        model="google/gemini-3.7-flash",
        provider="gemini",
    )
    command = drivers.TRANSPORTS[drivers.HARNESS_HERMES].command(
        spec,
        tools_enabled=True,
        system_prompt="k",
        max_turns=7,
        store_root=tmp_path / "store",
        answer_file=tmp_path / "a.txt",
    )
    assert command[command.index("--model") + 1] == "gemini/google/gemini-3.7-flash"


def test_hermes_leaves_the_model_alone_when_no_provider_is_pinned(tmp_path):
    spec = drivers.DriverSpec(name=drivers.HARNESS_HERMES, binary="hermes", model="some-model")
    command = drivers.TRANSPORTS[drivers.HARNESS_HERMES].command(
        spec,
        tools_enabled=True,
        system_prompt="k",
        max_turns=7,
        store_root=None,
        answer_file=tmp_path / "a.txt",
    )
    assert command[command.index("--model") + 1] == "some-model"





