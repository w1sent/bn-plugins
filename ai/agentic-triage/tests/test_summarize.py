"""Unit tests for summarize.py -- runs outside Binary Ninja.

Per docs/common-issues.md, run this from inside `tests/` (not the plugin
root) so pytest doesn't try to import the plugin package's `__init__.py`
(which imports `binaryninja`) as an ancestor package:

    cd ai/agentic-triage/tests && python3 -m pytest test_summarize.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from summarize import estimate_tokens, truncate_to_tokens  # noqa: E402


def test_estimate_tokens_counts_words():
    assert estimate_tokens("one two three") == 3
    assert estimate_tokens("") == 0


def test_truncate_returns_unchanged_when_within_budget():
    text = "one two three"
    assert truncate_to_tokens(text, 10) == text


def test_truncate_returns_unchanged_when_exactly_at_budget():
    text = "one two three"
    assert truncate_to_tokens(text, 3) == text


def test_truncate_cuts_and_appends_notice():
    text = " ".join(f"word{i}" for i in range(20))
    result = truncate_to_tokens(text, 5)
    assert result.startswith("word0 word1 word2 word3 word4")
    assert "truncated" in result
    assert "word19" not in result
