"""A record name is never an f-string at a call site: the store derives it."""

from __future__ import annotations

import ast
import pathlib

PACKAGES = pathlib.Path(__file__).resolve().parents[2] / "packages"


def _is_record_call(node: ast.Call) -> bool:
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr in {"record", "record_many"}


def test_no_fstring_names_in_store_calls():
    offenders: list[str] = []
    for path in PACKAGES.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_record_call(node):
                continue
            for keyword in node.keywords:
                if keyword.arg != "name":
                    continue
                if isinstance(keyword.value, ast.JoinedStr):
                    offenders.append(f"{path}:{keyword.value.lineno}")
                if isinstance(keyword.value, ast.Call):
                    target = keyword.value.func
                    if not isinstance(target, ast.Attribute):
                        continue
                    if target.attr in {"format", "join"}:
                        offenders.append(f"{path}:{keyword.value.lineno}")
    assert offenders == [], offenders
