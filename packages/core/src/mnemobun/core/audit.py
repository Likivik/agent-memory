"""Answer-audit (P2, design doc §8.1 / decisions 8): verify a drafted answer against memory.

Dual retrieval (the question AND the drafted answer are both keys — arXiv:2611.05636's
verify-then-regenerate), a three-way label (`supported | conflicting | unsupported`), and an
abstain default: a labeler error or an unparseable reply never hardens into a verdict, and a
verdict never changes standing. The labeler arrives as a plain callable so core stays
reasoner-free (Invariant 5); the executor binds its host/endpoint reasoner in.
"""

from __future__ import annotations

import collections.abc

from .access_log import AccessEntry, AccessLog
from .config import Config
from .database import Database
from .recall import Recall

LABEL_SUPPORTED = "supported"
LABEL_CONFLICTING = "conflicting"
LABEL_UNSUPPORTED = "unsupported"
LABEL_ABSTAIN = "abstain"
LABELS = (LABEL_SUPPORTED, LABEL_CONFLICTING, LABEL_UNSUPPORTED)
KIND_VERIFY = "verify"

PROMPT_TEMPLATE = """Memory excerpts (numbered):
{evidence}

Draft answer:
{draft}

Question:
{query}

Label the draft answer strictly as one word, one of:
- supported: the excerpts contain the answer and nothing contradicts it
- conflicting: the excerpts contain the answer but contradict the draft
- unsupported: the excerpts neither contain nor contradict the answer
Label:"""


def verify(
    store,
    draft: str,
    query: str,
    labeler: collections.abc.Callable[[str], str] | None,
    *,
    writer: str = "",
    at: str | None = None,
    config: Config | None = None,
) -> dict[str, object]:
    """Audit `draft` against the active memory surface. Deterministic code owns retrieval,
    the session cap, and logging; the labeler only classifies evidence already retrieved."""
    settings = (config or store.config).standing
    moment = at or store.clock.now().isoformat()
    recall = Recall(store)

    evidence_blocks: list[str] = []
    names: list[str] = []
    for key in (query, draft):
        for hit in recall.recall(key, limit=store.config.recall.default_limit, log=False):
            if hit.name in names:
                continue
            names.append(hit.name)
            evidence_blocks.append(f"[{len(names)}] {hit.name}: {hit.abstract}")

    session_cap = settings.audit_max_per_session
    with Database(store.layout).connect() as connection:
        log = AccessLog(connection)
        used = sum(1 for row in log.entries() if row["kind"] == KIND_VERIFY)
        if used >= session_cap:
            return _result(LABEL_ABSTAIN, names, evidence_blocks,
                           reason="session audit budget spent", at=moment, writer=writer)
        if not evidence_blocks:
            entry = AccessEntry(at=moment, name="", query=query,
                                kind=KIND_VERIFY, writer=writer)
            log.append([entry])
            return _result(LABEL_UNSUPPORTED, [], [],
                           reason="no memory hits", at=moment, writer=writer)
        if labeler is None:
            entry = AccessEntry(at=moment, name="", query=query,
                                kind=KIND_VERIFY, writer=writer)
            log.append([entry])
            return _result(LABEL_ABSTAIN, names, evidence_blocks,
                           reason="no labeler bound", at=moment, writer=writer)
        label = _label(labeler, PROMPT_TEMPLATE.format(
            evidence="\n".join(evidence_blocks), draft=draft, query=query))
        log.append([AccessEntry(
            at=moment, name=names[0], query=query, kind=KIND_VERIFY, writer=writer)])
    return _result(label, names, evidence_blocks, reason=None, at=moment, writer=writer)


def _label(labeler: collections.abc.Callable[[str], str], prompt: str) -> str:
    try:
        reply = labeler(prompt)
    except Exception:  # noqa: BLE001 — any labeler failure must abstain, never fabricate
        return LABEL_ABSTAIN
    lowered = str(reply).strip().lower()
    # Longest-first: "unsupported" contains "supported".
    for marker in (LABEL_UNSUPPORTED, LABEL_CONFLICTING, LABEL_SUPPORTED):
        if marker in lowered:
            return marker
    return LABEL_ABSTAIN


def _result(label: str, names: list[str], evidence: list[str], *, reason: str | None,
            at: str, writer: str) -> dict[str, object]:
    return {
        "label": label,
        "evidence": names,
        "excerpts": evidence,
        "reason": reason,
        "at": at,
        "writer": writer,
    }
