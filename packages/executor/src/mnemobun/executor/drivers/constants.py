"""Every literal the driver and the transports share: harness names, binaries, prompts."""

from __future__ import annotations

import logging

HARNESS_CODEX = "codex"
HARNESS_HERMES = "hermes"
HARNESS_MUSE_CODE = "muse-code"

BINARIES = {
    HARNESS_CODEX: ("codex", "gpt-5.6-sol"),
    HARNESS_HERMES: ("hermes", "google/gemini-3.7-flash"),
    HARNESS_MUSE_CODE: ("muse", ""),
}
MEM_TOOL_PATTERN = "Bash(mem:*)"
HERMES_TOOLSETS = "terminal"
HERMES_WRITE_SERVER_NAME = "mnemobun-write"
HERMES_MANAGE_SERVER_NAME = "mnemobun-manage"
HERMES_NATIVE_MAX_TURNS = 8
HERMES_NATIVE_TOOL_REQUIREMENT = "Hermes native tools require Hermes Agent 0.22.2 or newer"
# Kept for callers that imported the Write-specific name before Manage reused the same runtime.
HERMES_NATIVE_WRITE_REQUIREMENT = HERMES_NATIVE_TOOL_REQUIREMENT
HERMES_DATA_TRAINING_REQUIREMENT = (
    "Hermes contributor models require allow_data_training = true"
)
CODEX_SANDBOX_TOOLS = "workspace-write"
CODEX_SANDBOX_READONLY = "read-only"
BARE_SYSTEM_PROMPT = "You are a helpful assistant. Answer the user directly and concisely."
PROMPT_PLACEHOLDER = "<<prompt>>"
PROMPT_SEPARATOR = "\n\n"
ERROR_EXCERPT = 400
ANSWER_FILENAME = "answer.txt"
PROMPT_FILENAME = "prompt.txt"
INSTRUCTIONS_FILENAME = "instructions.md"
CODEX_TOOL_APPROVAL = "approve"
CODEX_DISABLED_FEATURES = (
    "apps",
    "plugins",
    "multi_agent",
    "hooks",
    "memories",
    "shell_tool",
    "unified_exec",
    "skill_search",
    "skill_mcp_dependency_install",
    "browser_use",
    "computer_use",
    "view_image",
    "image_generation",
    "goals",
)
MUSE_TOOLSET_SETTING = "run.toolset"
MUSE_NATIVE_TOOL_REQUIREMENT = "Muse native tools require Muse Code 1.4.4 or newer"
MUSE_RUNTIME_TMPDIR = "/var/tmp"
MUSE_NATIVE_MAX_MODEL_STEPS = 8



LOGGER = logging.getLogger(__name__)
