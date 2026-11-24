"""Declarative config panel for the mnemobun memory provider.

Loaded by path (never imported as a package): this file may import only the
pure-data schema module. Storage is "provider": the plugin's own
read_config_fields / write_config_fields own the file layout.
"""

from __future__ import annotations

from plugins.memory.config_schema import (
    KIND_NUMBER,
    KIND_TEXT,
    STORAGE_PROVIDER,
    ProviderConfigSchema,
    ProviderField,
)

CONFIG_SCHEMA = ProviderConfigSchema(
    name="mnemobun",
    label="mnemobun",
    storage=STORAGE_PROVIDER,
    docs_url="https://github.com/Likivik/mnemobun",
    fields=(
        ProviderField(
            key="model",
            label="Model",
            kind=KIND_TEXT,
            inline=True,
            group="Model",
            description="Model for memory jobs. Empty: deterministic-only, jobs refuse loudly.",
        ),
        ProviderField(
            key="endpoint",
            label="Endpoint URL",
            kind=KIND_TEXT,
            inline=True,
            group="Model",
            description="User-owned OpenAI-compatible endpoint for memory jobs.",
        ),
        ProviderField(
            key="key_env",
            label="API key env var",
            kind=KIND_TEXT,
            inline=True,
            group="Model",
            description="Name of the env var holding the endpoint API key (never the key itself).",
        ),
        ProviderField(
            key="distill_model",
            label="Feed/distill model override",
            kind=KIND_TEXT,
            group="Model",
            description="Defaults to Model when empty.",
        ),
        ProviderField(
            key="dream_model",
            label="Dream model override",
            kind=KIND_TEXT,
            group="Model",
            description="Defaults to Model when empty.",
        ),
        ProviderField(
            key="max_calls_per_run",
            label="Max model calls per run",
            kind=KIND_NUMBER,
            inline=True,
            group="Spend guard",
            description="Hard cap per run. A refused run counts as one call.",
        ),
        ProviderField(
            key="max_tokens_per_day",
            label="Max input tokens per day",
            kind=KIND_NUMBER,
            inline=True,
            group="Spend guard",
            description="Hard cap on input tokens per day.",
        ),
        ProviderField(
            key="store_path",
            label="Store path",
            kind=KIND_TEXT,
            group="Store",
            description="Filesystem path of the mnemobun store.",
        ),
    ),
)
