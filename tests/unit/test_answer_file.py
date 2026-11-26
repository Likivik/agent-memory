"""Answer-file handling: the codex dialect reads the file its host writes."""

from mnemobun.executor.agents import DIALECTS, HARNESS_CODEX


def _dialect():
    chosen = DIALECTS[HARNESS_CODEX]
    return chosen() if isinstance(chosen, type) else chosen


def test_answer_prefers_the_answer_file(tmp_path):
    answer_file = tmp_path / "answer.txt"
    answer_file.write_text("the answer\n", encoding="utf-8")
    assert _dialect().answer("ignored stdout", answer_file) == "the answer"


def test_answer_empty_without_file_or_text(tmp_path):
    answer_file = tmp_path / "answer.txt"
    assert _dialect().answer("stdout only", answer_file) == ""
    answer_file.write_text("   \n", encoding="utf-8")
    assert _dialect().answer("stdout only", answer_file) == ""
