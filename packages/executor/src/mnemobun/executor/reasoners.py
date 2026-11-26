"""Two ways to supply the reading a sleep needs, both outside the core (Invariant 5).

They fail differently, which is why both exist. A driver reasoner spends the agent the user is
already running: no key, no second bill, and the reasoning shows up in that agent's own
transcript where it can be read. An endpoint reasoner answers on a cron at three in the
morning when no agent session exists, at the cost of a credential and a network hop.

Neither carries algorithm. For Write negotiation both run as standard tool-use agents over the
core's Write toolkit — the endpoint through native function calling in a loop the executor
drives, the driver through its own loop with the toolkit served over MCP. Everything about what
a tool does and which operations to believe stays in the core.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys
import tempfile

from mnemobun.core.config import EXECUTOR_ENV_VAR
from mnemobun.core.errors import ReasonerUnavailableError
from mnemobun.core.manage_toolkit import ManageReviewToolkit
from mnemobun.core.reasoning import ReviewRuntime
from mnemobun.core.toolkit import WriteToolkit

from .drivers import BINARIES, Driver, DriverResult, DriverSpec, ToolServer

CHAT_COMPLETIONS = "/chat/completions"
DEFAULT_ENDPOINT_MODEL = "google/gemini-2.5-flash"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_ENDPOINT_ATTEMPTS = 3
ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"
EMPTY = ""
TOOL_SERVER_NAME = "memory"
WRITE_SESSION_MODULE = "mnemobun.mcp.write_session"
MANAGE_SESSION_MODULE = "mnemobun.mcp.manage_session"
MANAGE_TOOL_SERVER_NAME = "memory_review"
MALFORMED_ARGUMENTS = "tool arguments must be a JSON object"


@dataclasses.dataclass
class DriverReasoner:
    """The consuming agent's own CLI, run headless for one turn."""

    driver: Driver
    max_turns: int = 1

    def __call__(self, prompt: str) -> str:
        result = self.driver.run(
            prompt,
            tools_enabled=False,
            max_turns=self.max_turns,
            environment={EXECUTOR_ENV_VAR: "1"},
        )
        if not result.ok:
            raise _driver_failure(self.driver, result)
        if not result.text.strip():
            name = getattr(self.driver, "name", "configured driver")
            raise ReasonerUnavailableError(f"driver reasoner returned an empty response for {name}")
        return result.text

    @classmethod
    def for_harness(
        cls,
        name: str,
        model: str = EMPTY,
        provider: str = EMPTY,
        allow_data_training: bool = False,
    ) -> DriverReasoner:
        """A harness is named by its driver, not by its binary."""
        if name not in BINARIES:
            raise ReasonerUnavailableError(f"unsupported driver reasoner {name!r}")
        binary, default_model = BINARIES[name]
        return cls(
            driver=Driver(
                DriverSpec(
                    name=name,
                    binary=binary,
                    model=model or default_model,
                    provider=provider,
                    allow_data_training=allow_data_training,
                )
            )
        )


@dataclasses.dataclass
class ToolDriverReasoner(DriverReasoner):
    """The driver CLI as a tool-use agent: one run per batch, the toolkit served over MCP."""

    def converse(self, instructions: str, material: str, toolkit: WriteToolkit) -> None:
        self._converse(
            instructions,
            material,
            toolkit,
            server_name=TOOL_SERVER_NAME,
            module=WRITE_SESSION_MODULE,
        )

    def review_converse(
        self, instructions: str, material: str, toolkit: ManageReviewToolkit
    ) -> ReviewRuntime:
        """Run one bounded native Dream review and return measured Driver wall time."""
        result = self._converse(
            instructions,
            material,
            toolkit,
            server_name=MANAGE_TOOL_SERVER_NAME,
            module=MANAGE_SESSION_MODULE,
            timeout_seconds=toolkit.request.limits.timeout_seconds,
            host_analytics_enabled=False,
        )
        usage = result.usage
        phases = result.phases
        return ReviewRuntime(
            duration_seconds=result.seconds,
            startup_seconds=phases.startup_seconds if phases else None,
            model_wait_seconds=phases.model_wait_seconds if phases else None,
            mcp_seconds=phases.mcp_seconds if phases else None,
            shutdown_seconds=phases.shutdown_seconds if phases else None,
            agent_turns=usage.turns if usage else None,
            input_tokens=usage.input_tokens if usage else None,
            cached_input_tokens=usage.cached_input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
        )

    def _converse(
        self,
        instructions: str,
        material: str,
        toolkit: WriteToolkit | ManageReviewToolkit,
        *,
        server_name: str,
        module: str,
        timeout_seconds: float | None = None,
        host_analytics_enabled: bool = True,
    ) -> DriverResult:
        with tempfile.TemporaryDirectory() as batch:
            directory = pathlib.Path(batch)
            toolkit.save_seed(directory)
            server = ToolServer(
                name=server_name,
                command=sys.executable,
                args=("-m", module, str(directory)),
                tools=tuple(spec.name for spec in toolkit.catalogue()),
                host_analytics_enabled=host_analytics_enabled,
            )
            result = self.driver.converse(
                material,
                system_prompt=instructions,
                server=server,
                environment={EXECUTOR_ENV_VAR: "1"},
                timeout_seconds=timeout_seconds,
            )
            if not result.ok:
                raise _driver_failure(self.driver, result)
            toolkit.absorb_directory(directory)
            return result


def _driver_failure(driver: Driver, result: DriverResult) -> ReasonerUnavailableError:
    name = getattr(driver, "name", "configured driver")
    detail = f": {result.error.strip()}" if result.error.strip() else ""
    return ReasonerUnavailableError(
        f"driver reasoner failed for {name}{detail}; run mem doctor --driver {name}"
    )
