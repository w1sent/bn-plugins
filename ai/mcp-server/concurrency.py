"""Server-wide tool-call serialization (v1: a single global lock), plus a
shared "log every tool call" wrapper applied at registration time so it
covers every tool -- current and future -- without each tool needing to
remember to log itself.

Async jobs (see scripting.py) are the deliberate exception to serialization
-- their whole point is to run without holding this lock, so other tool
calls stay responsive while a long script runs.
"""

import threading
from functools import wraps

import binaryninja

EXECUTION_LOCK = threading.RLock()

_ARG_PREVIEW_LIMIT = 120


def serialized(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with EXECUTION_LOCK:
            return fn(*args, **kwargs)

    return wrapper


def _preview(value) -> str:
    text = repr(value)
    return text if len(text) <= _ARG_PREVIEW_LIMIT else text[: _ARG_PREVIEW_LIMIT - 3] + "..."


def log_tool_call(fn):
    """Log every call to `fn` as an INFO line in BN's own log console (the
    GUI's Log panel / headless stdout -- not just our per-plugin file).
    Apply this at tool registration time, not ad hoc per tool, so logging
    coverage doesn't depend on each tool remembering to add it."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        parts = [_preview(a) for a in args] + [f"{k}={_preview(v)}" for k, v in kwargs.items()]
        binaryninja.log_info(f"[mcp-server] tool call: {fn.__name__}({', '.join(parts)})")
        return fn(*args, **kwargs)

    return wrapper
