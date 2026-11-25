"""Every tunable in the system. No knob lives anywhere else."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import pathlib
import tomllib
from typing import Any

CONFIG_FILENAME = "config.toml"
STORE_ENV_VAR = "MNEMOBUN_STORE"
EXECUTOR_ENV_VAR = "MNEMOBUN_EXECUTOR"
MUSE_SETTINGS_ENV_VAR = "MNEMOBUN_MUSE_SETTINGS"
PINNED_FIELD = "pinned"
PIN_ORDER_FIELD = "pin_order"
PIN_ORDER_DEFAULT = 1000
PINNED_TYPES = frozenset({"claim"})
PINNED_REFUSED_STANDING = frozenset({"contested", "retracted", "superseded"})
PINNED_DATE_CHARS = 10
PINNED_ROSTER_FILENAME = "pins.json"
PINNED_ROSTER_INDENT = 2
DEFAULT_SLUG_MAX_LENGTH = 80
SLUG_WIDEN_FACTOR = 4
SLUG_DIGEST_LENGTH = 8
SLUG_MIN_KEEP = 1
REASONER_PLUGIN = "plugin"  # the Hermes plugin injects ctx.llm
REASONER_DIALECTS = ("claude-code", "codex")  # an external CLI agent answers
COORDINATION_LOCK_POLL_SECONDS = 0.02
DREAM_CLAIM_ID_LENGTH = 20
DREAM_ERROR_MAX_CHARS = 1000
STATE_JSON_INDENT = 2
DEFAULT_STORE = "~/mnemobun-store"
@dataclasses.dataclass
class StorageConfig:
    schemas_dirname: str = "schemas"
    max_depth: int = 3
    field_sources: dict[str, str] = dataclasses.field(
        default_factory=lambda: {
            "project": "system",
            "user": "system",
            "date": "system",
            "topic": "docket",
            "category": "docket",
            "source": "docket",
        }
    )
    default_group: str = "general"
    default_project: str = "default"
    default_user: str = "default"
    slug_max_length: int = 80
    abstract_max_chars: int = 240
    archive_sessions_enabled: bool = True
    lock_timeout_seconds: float = 30.0
    lock_poll_seconds: float = 0.02


@dataclasses.dataclass
class IndexConfig:
    hash_prefix_length: int = 16
    chunk_min_chars: int = 200
    bm25_abstract_weight: float = 2.0
    bm25_body_weight: float = 1.0
    tokenizer: str = "ascii"
    vector_enabled: bool = False
    vector_model: str = "BAAI/bge-small-en-v1.5"
    embedder_backend: str = "fastembed"  # "fastembed" (local ONNX) or "http" (OpenAI-compatible)
    embedder_url: str = ""  # e.g. http://127.0.0.1:8081 for a local llama-server
    embedder_timeout_seconds: float = 60.0
    embedder_batch_size: int = 32


@dataclasses.dataclass
class MemoryMdConfig:
    budget_bytes: int = 8192
    max_lines: int = 120
    header: str = "# MEMORY.md"


@dataclasses.dataclass
class BudgetConfig:
    """Hard bounds are calls + input tokens."""

    max_calls_per_run: float = 40.0
    max_tokens_per_day: float = 2000000.0
    est_usd_per_day: float = 1.0
    est_usd_per_month: float = 10.0


@dataclasses.dataclass
class UsageConfig:
    initial: float = 1.0
    floor: float = 0.05
    ceiling: float = 5.0
    boost_step: float = 0.5
    decay_step: float = 0.1
    decay_after_days: float = 30.0
    # Feed trigger: perception signal + token budget + quiet (P13.5c).
    perception_user_text_weight: float = 2.0
    perception_tool_noise_weight: float = 0.1
    perception_length_saturation_chars: float = 400.0
    perception_novelty_weight: float = 1.5
    perception_repetition_penalty: float = 0.5
    signal_threshold: float = 30.0
    quiet_seconds: float = 1800.0
    token_budget: float = 80000.0
    backstop_turns: float = 50.0
    # Write-time importance (Park's 1-10 poignancy scale; 0 = unrated, neutral).
    importance_initial: float = 0.0
    importance_floor: float = 0.0
    importance_ceiling: float = 10.0
    importance_score_scale: float = 10.0


@dataclasses.dataclass
class RecallConfig:
    default_limit: int = 8
    candidate_pool_multiplier: int = 10
    recency_half_life_days: float = 180.0
    recency_decay_base: float = 0.5
    recency_floor: float = 0.25
    memory_md_weight_floor: float = 0.75
    synthesis_hint: bool = True
    context_full_text_entries: int = 4
    injection_enabled: bool = True
    injection_budget_bytes: int = 8192
    pinned_max_bytes: int = 2048  # the pinned-rules block: ~500 tokens, ~10 rules
    anchor_context_chars: int = 160
    snippet_max_chars: int = 400


@dataclasses.dataclass
class ManageConfig:
    pin_min_citations: int = 3
    pin_min_queries: int = 2  # distinct queries that cited the claim
    max_pins_per_sleep: int = 2
    max_unpins_per_sleep: int = 2  # a claim cited this often is worth a pin ruling
    auto_dream: bool = True
    claim_lease_seconds: float = 1800.0
    trigger_min_hours: float = 24.0
    trigger_min_sessions: int = 3
    cluster_min_files: int = 5
    cluster_min_shared_tokens: int = 2
    merge_proposal_similarity: float = 0.75
    link_cooccurrence_min: int = 2
    abstract_min_words: int = 3
    max_boosts_per_sleep: int = 3
    max_merges_per_sleep: int = 3
    max_supersedes_per_sleep: int = 5
    max_splits_per_sleep: int = 2
    max_deletes_per_sleep: int = 3
    max_accepts_per_sleep: int = 10
    max_conflicts_per_sleep: int = 5
    split_min_sections: int = 3
    review_max_steps: int = 8
    review_max_tool_calls: int = 24
    review_tool_result_chars: int = 8000
    review_evidence_chars: int = 32000
    review_raw_session_evidence: bool = False
    git_commit: bool = True
    dream_report_dirname: str = "dream-reports"


@dataclasses.dataclass
class WriteJobsConfig:
    jobs_dirname: str = "write-jobs"
    lease_seconds: float = 1800.0
    heartbeat_seconds: float = 300.0
    max_attempts: int = 3
    backoff_base_seconds: float = 30.0
    backoff_max_seconds: float = 3600.0
    backoff_jitter: float = 0.25
    retention_days: float = 14.0
    trace_enabled: bool = True
    trace_bodies: bool = False
    trace_max_bytes: int = 262144
    error_max_chars: int = 1000


@dataclasses.dataclass
class WriteConfig:
    watermark_dirname: str = "watermarks"
    session_archive_enabled: bool = True
    hook_timeout_seconds: float = 20.0
    batch_hint: bool = True
    max_distill_input_chars: int = 24000
    reconcile_entries: int = 8
    reconcile_query_chars: int = 2000
    repair_rounds: int = 1
    pending_dirname: str = "pending"
    pending_message_threshold: int = 20
    pending_token_threshold: int = 4000
    chars_per_token: int = 4
    idle_seconds: float = 900.0
    distill_on_boundary: bool = True
    slot_table: bool = True
    event_lane: bool = True
    max_rounds: int = 3
    tool_result_chars: int = 4000
    jobs: WriteJobsConfig = dataclasses.field(default_factory=WriteJobsConfig)


@dataclasses.dataclass
class OperationExecutorConfig:
    reasoner: str = ""
    timeout_seconds: float = 0.0


@dataclasses.dataclass
class ExecutorConfig:
    reasoner: str = "claude-code"
    provider: str = ""
    provider_source: str = "unset"  # a CLI dialect, or "plugin" for ctx.llm
    model: str = ""  # no silent default
    model_source: str = "unset"  # chat | cli | gui | unset
    timeout_seconds: float = 120.0
    command: str = "mnemobun distill"
    attempts: int = 3
    write: OperationExecutorConfig = dataclasses.field(default_factory=OperationExecutorConfig)
    manage: OperationExecutorConfig = dataclasses.field(default_factory=OperationExecutorConfig)


@dataclasses.dataclass
class ProviderConfig:
    """In-process Hermes provider knobs (design decisions 5 and 7). A separate section so
    the asserted recall_fingerprint() default is untouched; Config.fingerprint() changes,
    which test_memory_systems tolerates because it compares like-for-like defaults."""

    prefetch_budget_bytes: int = 1500
    prefetch_top_k: int = 5


@dataclasses.dataclass
class StandingConfig:
    """Standing-machine knobs (design doc v1.2, decisions 4–7). Excluded from the recall
    fingerprint: retrieval shape is unchanged — standing only reweights final scores."""

    penalty_contested: float = 0.5
    penalty_proposed: float = 0.75
    penalty_retracted: float = 0.25
    penalty_superseded: float = 0.25
    audit_max_per_session: int = 3


@dataclasses.dataclass
class Config:
    storage: StorageConfig = dataclasses.field(default_factory=StorageConfig)
    index: IndexConfig = dataclasses.field(default_factory=IndexConfig)
    memory_md: MemoryMdConfig = dataclasses.field(default_factory=MemoryMdConfig)
    usage: UsageConfig = dataclasses.field(default_factory=UsageConfig)
    budget: BudgetConfig = dataclasses.field(default_factory=BudgetConfig)
    recall: RecallConfig = dataclasses.field(default_factory=RecallConfig)
    manage: ManageConfig = dataclasses.field(default_factory=ManageConfig)
    write: WriteConfig = dataclasses.field(default_factory=WriteConfig)
    executor: ExecutorConfig = dataclasses.field(default_factory=ExecutorConfig)
    standing: StandingConfig = dataclasses.field(default_factory=StandingConfig)
    provider: ProviderConfig = dataclasses.field(default_factory=ProviderConfig)

    @classmethod
    def default(cls) -> Config:
        return cls()

    @classmethod
    def load(cls, store_root: pathlib.Path) -> Config:
        config = cls.default()
        path = pathlib.Path(store_root) / CONFIG_FILENAME
        if not path.exists():
            return config
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        for section_name, values in raw.items():
            section = getattr(config, section_name, None)
            if section is None or not dataclasses.is_dataclass(section):
                raise ValueError(f"unknown config section: {section_name}")
            _load_section(section, values, section_name)
        config.validate_index()
        return config

    def validate_index(self) -> None:
        if not isinstance(self.index.vector_enabled, bool):
            raise ValueError("index.vector_enabled must be a boolean")
        if not isinstance(self.index.vector_model, str) or not self.index.vector_model.strip():
            raise ValueError("index.vector_model must be a non-empty string")
        from .tokenization import SUPPORTED_TOKENIZERS

        if self.index.tokenizer not in SUPPORTED_TOKENIZERS:
            raise ValueError(
                f"index.tokenizer must be one of {sorted(SUPPORTED_TOKENIZERS)}, "
                f"got {self.index.tokenizer!r}"
            )
        if not isinstance(self.manage.review_raw_session_evidence, bool):
            raise ValueError("manage.review_raw_session_evidence must be a boolean")
        self._validate_write_jobs()

    def _validate_write_jobs(self) -> None:
        jobs = self.write.jobs
        bounds = (
            ("lease_seconds", jobs.lease_seconds),
            ("heartbeat_seconds", jobs.heartbeat_seconds),
            ("retention_days", jobs.retention_days),
            ("trace_max_bytes", jobs.trace_max_bytes),
            ("error_max_chars", jobs.error_max_chars),
        )
        for knob, value in bounds:
            if value <= 0:
                raise ValueError(f"write.jobs.{knob} must be positive")
        if jobs.max_attempts < 1:
            raise ValueError("write.jobs.max_attempts must allow at least one attempt")
        if jobs.backoff_base_seconds < 0:
            raise ValueError("write.jobs.backoff_base_seconds must not be negative")
        if jobs.backoff_max_seconds < jobs.backoff_base_seconds:
            raise ValueError("write.jobs.backoff_max_seconds must not sit below its base")
        if not 0 <= jobs.backoff_jitter < 1:
            raise ValueError("write.jobs.backoff_jitter must sit in the interval [0, 1)")
        if not jobs.jobs_dirname.strip():
            raise ValueError("write.jobs.jobs_dirname must be a non-empty string")

    def save(self, store_root: pathlib.Path) -> pathlib.Path:
        path = pathlib.Path(store_root) / CONFIG_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render_toml(self), encoding="utf-8")
        return path

    def fingerprint(self) -> str:
        payload = json.dumps(dataclasses.asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[: self.index.hash_prefix_length]

    def recall_fingerprint(self) -> str:
        """Hash of only the knobs that shape retrieval — the Invariant 9 drift guard."""
        payload = json.dumps(
            {
                "index": self._index_knobs_shaping_recall(),
                "recall": dataclasses.asdict(self.recall),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[: self.index.hash_prefix_length]

    def _index_knobs_shaping_recall(self) -> dict[str, object]:
        knobs = dataclasses.asdict(self.index)
        if not self.index.vector_enabled:
            for key in list(knobs):
                if key == "vector_enabled" or key.startswith(("vector_", "embedder_")):
                    del knobs[key]
        return knobs


def resolve_store_root(explicit: str | pathlib.Path | None = None) -> pathlib.Path:
    raw = str(explicit) if explicit else os.environ.get(STORE_ENV_VAR) or DEFAULT_STORE
    return pathlib.Path(raw).expanduser().resolve()


def _render_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_render_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(f"{_render_value(str(k))} = {_render_value(v)}" for k, v in value.items())
            + "}"
        )
    return json.dumps(str(value), ensure_ascii=False)


def _render_toml(config: Config) -> str:
    lines: list[str] = []
    for section_field in dataclasses.fields(config):
        section = getattr(config, section_field.name)
        _render_section(lines, section_field.name, section)
    return "\n".join(lines)


def _load_section(section: Any, values: object, path: str) -> None:
    if not isinstance(values, dict):
        raise ValueError(f"config section must be a table: {path}")
    known = {field.name for field in dataclasses.fields(section)}
    for key, value in values.items():
        if key not in known:
            raise ValueError(f"unknown config knob: {path}.{key}")
        current = getattr(section, key)
        if dataclasses.is_dataclass(current):
            _load_section(current, value, f"{path}.{key}")
        elif isinstance(value, dict) and not isinstance(current, dict):
            raise ValueError(f"config knob must not be a table: {path}.{key}")
        elif _has_declared_type(current, value):
            setattr(section, key, value)
        else:
            raise ValueError(f"config knob has the wrong type: {path}.{key}")


def _has_declared_type(current: object, value: object) -> bool:
    if isinstance(current, bool):
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if isinstance(current, int):
        return isinstance(value, int)
    if isinstance(current, float):
        return isinstance(value, int | float)
    if isinstance(current, str):
        return isinstance(value, str)
    return True


def _render_section(lines: list[str], path: str, section: Any) -> None:
    lines.append(f"[{path}]")
    children: list[tuple[str, object]] = []
    for knob in dataclasses.fields(section):
        value = getattr(section, knob.name)
        if dataclasses.is_dataclass(value):
            children.append((knob.name, value))
        else:
            lines.append(f"{knob.name} = {_render_value(value)}")
    lines.append("")
    for name, child in children:
        _render_section(lines, f"{path}.{name}", child)
