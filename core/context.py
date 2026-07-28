"""Cached AI "context prompt" for the current sample -- a condensed
overview (detected frameworks, libraries, other high-level metadata) meant
to be injected into every other AI tool's prompts, so they don't each have
to re-explore the binary. See docs/adr/0035-shared-evidence-store-and-context-prompt.md.

Layered, cheapest-first:
  1. `build_baseline` -- deterministic, rendered fresh from the evidence
     store (core/evidence.py) every time; never cached, never stale.
  2. `raw_enhancer_output` -- optional narrative from an AI exploration
     agent, cached because it's expensive to produce. Freely overwritten
     whenever the user reruns the enhancer.
  3. `user_edit` -- written only by the user (e.g. via the dedicated
     context-inspector plugin's UI), and used in preference to
     `raw_enhancer_output` whenever present, so a rerun of the enhancer
     can never silently clobber a manual edit.

`get_context_prompt()` is the one function other AI plugins should call --
it is read-only and must never trigger an enhancer run itself (that's a
user-initiated action from the context-inspector plugin).
"""

from __future__ import annotations

from datetime import datetime, timezone

from .evidence import get_all_evidence, latest_last_run

_KEY = "core.context_prompt"


def _load(bv) -> dict:
    data = bv.get_metadata(_KEY, None)
    return data if isinstance(data, dict) else {}


def build_baseline(bv) -> str:
    """Render a deterministic summary straight from the evidence store.
    Always recomputed -- cheap, so never cached."""
    evidence = get_all_evidence(bv)
    if not evidence:
        return ""

    lines = []
    for detector_id in sorted(evidence):
        findings = evidence[detector_id].get("findings") or []
        for finding in findings:
            lines.append(f"[{detector_id}] {finding}")
    return "\n".join(lines)


def record_enhancer_output(bv, text: str, last_run: str | None = None) -> None:
    """Store (overwriting) the AI enhancer's raw output. Never touches
    `user_edit`."""
    data = _load(bv)
    data["raw_enhancer_output"] = text
    data["last_run"] = last_run or datetime.now(timezone.utc).isoformat()
    bv.store_metadata(_KEY, data)


def get_enhancer_output(bv) -> str | None:
    return _load(bv).get("raw_enhancer_output")


def get_enhancer_last_run(bv) -> str | None:
    return _load(bv).get("last_run")


def set_user_edit(bv, text: str) -> None:
    data = _load(bv)
    data["user_edit"] = text
    bv.store_metadata(_KEY, data)


def get_user_edit(bv) -> str | None:
    return _load(bv).get("user_edit")


def clear_user_edit(bv) -> None:
    """Revert to whatever the AI/baseline output would produce."""
    data = _load(bv)
    if "user_edit" in data:
        del data["user_edit"]
        bv.store_metadata(_KEY, data)


def get_context_prompt(bv) -> str:
    """The effective context prompt every AI tool should read: the user's
    edit if one exists, else the cached enhancer output, else the
    deterministic baseline. Read-only -- never runs the enhancer."""
    data = _load(bv)
    if data.get("user_edit") is not None:
        return data["user_edit"]
    if data.get("raw_enhancer_output") is not None:
        return data["raw_enhancer_output"]
    return build_baseline(bv)


def is_stale(bv) -> bool | None:
    """Whether evidence has been recorded more recently than the cached
    enhancer output -- a passive signal for the UI to surface ("context
    may be outdated, re-run?"). Never triggers a rerun itself. Returns
    None if the enhancer has never run, since staleness is undefined."""
    enhancer_last_run = get_enhancer_last_run(bv)
    if enhancer_last_run is None:
        return None
    newest_evidence = latest_last_run(bv)
    if newest_evidence is None:
        return False
    return newest_evidence > enhancer_last_run
