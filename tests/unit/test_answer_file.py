"""Answer-file handling: the codex transport reads the file its harness writes."""

from mnemobun.executor.drivers import HARNESS_CODEX, TRANSPORTS


def _transport():
    chosen = TRANSPORTS[HARNESS_CODEX]
    return chosen() if isinstance(chosen, type) else chosen


def test_answer_prefers_the_answer_file(tmp_path):
    answer_file = tmp_path / "answer.txt"
    answer_file.write_text("the answer\n", encoding="utf-8")
    assert _transport().answer("ignored stdout", answer_file) == "the answer"


def test_answer_empty_without_file_or_text(tmp_path):
    answer_file = tmp_path / "answer.txt"
    assert _transport().answer("stdout only", answer_file) == ""
    answer_file.write_text("   \n", encoding="utf-8")
    assert _transport().answer("stdout only", answer_file) == ""
