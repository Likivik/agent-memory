"""Headless host drivers: one dialect module per host."""

from .base import *
from .base import _CodexTrace  # noqa: F401 - re-exported for the test suite
from .codex import *  # noqa: F403
from .hermes import *  # noqa: F403
from .muse import *  # noqa: F403

DIALECTS: dict[str, Dialect] = {
    HARNESS_CODEX: CodexDialect(),
    HARNESS_HERMES: HermesDialect(),
    HARNESS_MUSE_CODE: MuseCodeDialect(),
}
