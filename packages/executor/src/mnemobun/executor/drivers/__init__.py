"""Headless drivers: the harness shells out; it never speaks a model API itself.

A transport says how one harness is spoken to; a driver runs one. Adding a harness
means adding a transport module and one line here - never a branch inside Driver.
"""

from .codex import CodexTransport
from .constants import BINARIES, HARNESS_CODEX, HARNESS_HERMES, HARNESS_MUSE_CODE
from .driver import Driver
from .helpers import _CodexTrace, _run_codex_jsonl
from .hermes import HermesTransport
from .muse import MuseCodeTransport
from .transport import Transport, _count, _host_usage, _stream_result
from .types import DriverPhases, DriverResult, DriverSpec, DriverUsage, ToolServer

__all__ = [
    "BINARIES",
    "TRANSPORTS",
    "Driver",
    "_CodexTrace",
    "_count",
    "_host_usage",
    "_run_codex_jsonl",
    "_stream_result",
    "DriverPhases",
    "DriverResult",
    "DriverSpec",
    "DriverUsage",
    "Transport",
    "ToolServer",
    "HARNESS_CODEX",
    "HARNESS_HERMES",
    "HARNESS_MUSE_CODE",
]

TRANSPORTS: dict[str, Transport] = {
    HARNESS_CODEX: CodexTransport(),
    HARNESS_HERMES: HermesTransport(),
    HARNESS_MUSE_CODE: MuseCodeTransport(),
}
