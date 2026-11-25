"""Slug.of must always produce a name the store accepts."""

from __future__ import annotations

import pytest
from mnemobun.core.slug import Slug, is_valid_slug

HOSTILE = [
    "20261101_173738_8ba95851",
    "agent:mnemobun-xvgjl7k4:local:dm:local-" + "ab" * 32,
    "Привет, как дела?",
    "🔥🔥🔥",
    "...",
    "",
    "x" * 10_000,
    "-already-slugged-",
]


@pytest.mark.parametrize("text", HOSTILE)
def test_always_valid_and_bounded(text):
    slug = Slug.of(text, 80)
    assert is_valid_slug(slug.value)
    assert len(slug.value) <= 80


def test_identity_hints_never_collapse():
    first = Slug.of("Hello World", 80, identity=True).value
    second = Slug.of("hello-world", 80, identity=True).value
    assert first != second
    assert both_short_distinct(first, second)


def both_short_distinct(a: str, b: str) -> bool:
    return len(a) <= 80 and len(b) <= 80 and is_valid_slug(a) and is_valid_slug(b)


def test_digest_only_when_needed():
    assert Slug.of("short-name", 80).value == "short-name"
    assert "-" in Slug.of("y" * 200, 80).value
