"""Scriptable, headless hex-visualizer API -- no Qt/binaryninjaui dependency,
so it works from BN's execute_script (see CONTEXT.md's "Developing and
testing plugins" section) with no widget open. widget.py's sidebar panel
is a thin renderer over this.

BN loads this plugin's directory name ("hex-visualizer", with the hyphen)
as its module name, which isn't a valid `import` statement target -- reach
it via importlib instead:

    import importlib
    api = importlib.import_module("hex-visualizer.api")
    result = api.inspect(bv, 0x1000, 64)
    print(result.format_match, result.rows)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .core.logging import get_logger
from . import formats, inspector

logger = get_logger("hex_visualizer")

# Bounds how much of a selection is ever read/decoded for the scalar-type
# table -- a user can select an entire multi-hundred-MB binary in the hex
# view, and the table doesn't need more than a bounded prefix of that.
READ_LIMIT = 1 << 20  # 1 MiB

# Minimum bytes sniffed for format detection, independent of how short the
# user's actual selection is -- selecting just the first byte or two of a
# PNG at the right address should still trigger detection (and carving),
# not require hand-selecting the whole header.
SNIFF_WINDOW = 512

# Re-exported for convenience/introspection from execute_script; see
# formats.CARVE_MAX for the actual bound used during carving.
CARVE_MAX = formats.CARVE_MAX


@dataclass
class InspectionResult:
    start: int
    end: int
    truncated: bool  # True if `end - start` (the table's source data) exceeded READ_LIMIT
    format_match: Optional[formats.FormatMatch]
    rows: list  # list[inspector.InspectorRow] -- built from the literal selection, not the carve
    data: bytes  # preview bytes -- the full carved file if carving succeeded, else the sniff window
    carved_length: Optional[int]  # full extent found by carving, if any (may exceed len(data))
    carve_truncated: bool  # True if the carved extent exceeded CARVE_MAX and `data` was capped


def inspect(bv, start: int, length: int) -> InspectionResult:
    """Read up to READ_LIMIT bytes at `start` from `bv`, build the same
    scalar-type table the sidebar panel shows, and -- if the selection's
    start matches a known format's magic bytes -- carve the full media
    file (which may extend well past `length`) for preview rendering."""
    end = start + length
    if length <= 0:
        empty_rows = inspector.build_inspection_table(b"")
        return InspectionResult(start, end, False, None, empty_rows, b"", None, False)

    read_length = min(length, READ_LIMIT)
    data = bv.read(start, read_length)
    truncated = length > read_length
    rows = inspector.build_inspection_table(data)

    sniff_length = min(max(length, SNIFF_WINDOW), READ_LIMIT)
    sniff_data = data if sniff_length <= len(data) else bv.read(start, sniff_length)
    match = formats.detect(sniff_data)

    preview_data = data
    carved_length = None
    carve_truncated = False
    if match is not None:
        def read_more(offset, want):
            return bv.read(start + offset, want)

        carved_length = formats.carve_extent(match.kind, sniff_data, read_more)
        if carved_length:
            carve_read_length = min(carved_length, CARVE_MAX)
            carve_truncated = carved_length > CARVE_MAX
            preview_data = (
                sniff_data[:carve_read_length]
                if carve_read_length <= len(sniff_data)
                else bv.read(start, carve_read_length)
            )
        else:
            preview_data = sniff_data

    return InspectionResult(start, end, truncated, match, rows, preview_data, carved_length, carve_truncated)


def help():
    print(__doc__)
    print(inspect.__doc__)
