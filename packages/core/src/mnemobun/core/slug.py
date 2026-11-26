"""Kebab slug = stable id. Survives any move, because nothing about it encodes location."""

from __future__ import annotations

import dataclasses
import hashlib
import re
import unicodedata

from .config import (
    DEFAULT_SLUG_MAX_LENGTH,
    SLUG_DIGEST_LENGTH,
    SLUG_MIN_KEEP,
    SLUG_WIDEN_FACTOR,
)

_SEPARATORS = re.compile(r"[\s_/\\.]+")
_ILLEGAL = re.compile(r"[^a-z0-9-]+")
_RUNS = re.compile(r"-+")
VALID_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def slugify(text: str, max_length: int) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    lowered = _SEPARATORS.sub("-", folded.strip().lower())
    cleaned = _RUNS.sub("-", _ILLEGAL.sub("-", lowered)).strip("-")
    return cleaned[:max_length].strip("-")


def is_valid_slug(text: str) -> bool:
    return bool(VALID_SLUG.fullmatch(text))


@dataclasses.dataclass(frozen=True)
class Slug:
    """A name the store will always accept: kebab, bounded, never empty.

    Identity-bearing text (harness session ids, turn keys) carries a short digest of the
    *full* text, so two hints that normalise to the same prefix cannot share a name.
    """

    value: str

    @classmethod
    def of(
        cls, text: str, max_length: int = DEFAULT_SLUG_MAX_LENGTH, *, identity: bool = False
    ) -> Slug:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        base = slugify(text, max_length)
        widened = slugify(text, max_length * SLUG_WIDEN_FACTOR)
        if identity or len(widened) > max_length:
            keep = max(max_length - len(digest) - SLUG_MIN_KEEP, SLUG_MIN_KEEP)
            base = (slugify(text, keep).rstrip("-") + "-" + digest[:SLUG_DIGEST_LENGTH]).strip("-")
        if not base:
            base = "n-" + digest[:SLUG_DIGEST_LENGTH]
        return cls(base)
