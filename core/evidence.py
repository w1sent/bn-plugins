"""Shared evidence store for deterministic detectors (frameworks/*, YARA,
...) and the AI context-prompt enhancer, persisted in the BN metadata store
so it travels with the `.bndb` -- see docs/adr/0035-shared-evidence-store-and-context-prompt.md.

Each detector owns exactly one metadata key, `core.evidence.<detector_id>`,
so rerunning one detector overwrites only its own entry. There is no
central registry of detector ids: consumers discover entries by
prefix-scanning `bv.metadata`, which BN already provides.
"""

from __future__ import annotations

from datetime import datetime, timezone

_PREFIX = "core.evidence."


def _key(detector_id: str) -> str:
    return f"{_PREFIX}{detector_id}"


def record_evidence(bv, detector_id: str, findings, last_run: str | None = None) -> None:
    """Store (overwriting) this detector's findings.

    `findings` must be JSON-serializable (BN's Metadata type constraints).
    `last_run` defaults to the current UTC time in ISO-8601; pass it
    explicitly only for tests or replaying a recorded run.
    """
    entry = {
        "findings": findings,
        "last_run": last_run or datetime.now(timezone.utc).isoformat(),
    }
    bv.store_metadata(_key(detector_id), entry)


def get_evidence(bv, detector_id: str) -> dict | None:
    """Return `{"findings": ..., "last_run": ...}` for one detector, or
    None if it hasn't run yet."""
    return bv.get_metadata(_key(detector_id), None)


def get_all_evidence(bv) -> dict[str, dict]:
    """Return `{detector_id: {"findings": ..., "last_run": ...}}` for every
    detector that has ever recorded evidence on this `bv`."""
    return {
        key[len(_PREFIX):]: value
        for key, value in bv.metadata.items()
        if key.startswith(_PREFIX)
    }


def latest_last_run(bv) -> str | None:
    """Return the most recent `last_run` timestamp across all recorded
    evidence, or None if no detector has run yet. Used to compare against
    a cached context prompt's `last_run` for the passive staleness flag."""
    runs = [entry["last_run"] for entry in get_all_evidence(bv).values()]
    return max(runs) if runs else None
