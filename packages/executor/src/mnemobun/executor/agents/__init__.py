"""Headless host drivers: one dialect module per host."""

from .base import *
from .base import _CodexTrace  # noqa: F401 - re-exported for the test suite
from .codex import *  # noqa: F403
from .hermes import *  # noqa: F403
from .muse import *  # noqa: F403

DIALECTS: dict[str, Dialect] = {
    HOST_CODEX: CodexDialect(),
    HOST_HERMES: HermesDialect(),
    HOST_MUSE_CODE: MuseCodeDialect(),
}
