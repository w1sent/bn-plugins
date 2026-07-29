"""Token-budget enforcement for the AI-enhancer summary.

Approximate, dependency-free token counting (whitespace word count) rather
than a real tokenizer -- the enhancer's summary length only needs to be
kept roughly bounded (configurable via `agentic_triage.max_summary_tokens`),
not billed precisely. No `binaryninja` import, so this is unit-testable
outside BN.
"""

from __future__ import annotations

_TRUNCATION_NOTICE = "\n\n[... summary truncated to fit the configured token budget ...]"


def estimate_tokens(text: str) -> int:
    return len(text.split())


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate `text` to approximately `max_tokens` words. Returns `text`
    unchanged if it's already within budget."""
    words = text.split()
    if len(words) <= max_tokens:
        return text
    return " ".join(words[:max_tokens]) + _TRUNCATION_NOTICE
