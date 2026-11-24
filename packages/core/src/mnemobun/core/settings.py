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
    "model",
    "distill_model",
    "dream_model",
    "max_calls_per_run",
    "max_tokens_per_day",
    "endpoint",
    "key_env",
)


def apply_settings(store: Store, payload: dict[str, object], *, actor: str) -> dict[str, object]:
    """Validate, apply to the store config, audit once, save once."""
    unknown = set(payload) - set(SETTINGS_KEYS)
    if unknown:
        raise ValueError(f"unknown settings: {sorted(unknown)}")
    before = effective_settings(store)
    brain = store.config.executor
    for key in ("model", "distill_model", "dream_model"):
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()  # an explicit empty value clears (brain reads "" as unset)
        if key == "model":
            if brain.model != text:  # idempotent re-assert is a no-op
                brain.model_source = actor if text else "unset"
            brain.model = text
        else:
            getattr(brain, "write" if key == "distill_model" else "manage").model = text
    for key in ("endpoint", "key_env"):
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()  # an explicit empty value clears
        if key == "endpoint":
            if text:
                brain.reasoner = "endpoint"
            brain.endpoint = text
        else:
            brain.key_env = text
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
        "model": brain.model,
        "model_source": brain.model_source,
        "distill_model": brain.write.model,
        "dream_model": brain.manage.model,
        "max_calls_per_run": store.config.budget.max_calls_per_run,
        "max_tokens_per_day": store.config.budget.max_tokens_per_day,
        "endpoint": brain.endpoint,
        "key_env": brain.key_env,
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
