"""Memory settings: the ONE writer every surface funnels through.

The store config is the single source of truth (portable with the store);
``apply_settings`` is its only writer — GUI, chat and CLI are callers. Reads
pull via ``effective_settings``. The audit line is metadata for humans and is
never used for control flow.
"""

from __future__ import annotations

import json

from mnemobun.core.store import Store

SETTINGS_KEYS = (
    "provider",
    "model",
    "max_calls_per_run",
    "max_tokens_per_day",
)


def apply_settings(store: Store, payload: dict[str, object], *, actor: str) -> dict[str, object]:
    """Validate, apply to the store config, audit once, save once."""
    unknown = set(payload) - set(SETTINGS_KEYS)
    if unknown:
        raise ValueError(f"unknown settings: {sorted(unknown)}")
    before = effective_settings(store)
    brain = store.config.executor
    value = payload.get("model")
    if value is not None:
        text = str(value).strip()  # an explicit empty value clears (brain reads "" as unset)
        if brain.model != text:  # idempotent re-assert is a no-op
            brain.model_source = actor if text else "unset"
        brain.model = text
    value = payload.get("provider")
    if value is not None:
        text = str(value).strip()
        if brain.provider != text:
            brain.provider_source = actor if text else "unset"
        brain.provider = text
    for key in ("max_calls_per_run", "max_tokens_per_day"):
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text:  # an explicit empty value resets the cap to its default
            setattr(store.config.budget, key, getattr(type(store.config.budget)(), key))
            continue
        try:
            number = float(text)
        except ValueError as error:
            raise ValueError(f"{key} must be a number") from error
        if number <= 0:
            raise ValueError(f"{key} must be positive")
        setattr(store.config.budget, key, number)
    store.config.save(store.root)
    after = effective_settings(store)
    _audit(store, actor=actor, before=before, after=after)
    return after


def effective_settings(store: Store) -> dict[str, object]:
    """Pull the current settings from the store. Every surface reads this."""
    brain = store.config.executor
    return {
        "provider": brain.provider,
        "provider_source": brain.provider_source,
        "model": brain.model,
        "model_source": brain.model_source,
        "max_calls_per_run": store.config.budget.max_calls_per_run,
        "max_tokens_per_day": store.config.budget.max_tokens_per_day,
    }


def _audit(store: Store, *, actor: str, before: dict, after: dict) -> None:
    """Append-only settings history. Metadata only."""
    changed = {
        key: {"from": before.get(key), "to": after.get(key)}
        for key in after
        if before.get(key) != after.get(key)
    }
    if not changed:
        return
    path = store.root / ".state" / "settings-audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": store.clock.now().isoformat(), "actor": actor, "changed": changed}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
