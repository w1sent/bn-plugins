"""Hex+ASCII dump formatting for the triage agent's read_data tool.

Pure stdlib, no `binaryninja`/`.core` imports, so it's unit-testable
outside BN -- same pattern as summarize.py.
"""

from __future__ import annotations


def format_hexdump(data: bytes, base_addr: int = 0, width: int = 16) -> str:
    """Classic hex+ASCII dump: `<addr>: <hex bytes>  <ascii>`, `width`
    bytes per row, non-printable bytes shown as `.` in the ASCII column."""
    lines = []
    for offset in range(0, len(data), width):
        chunk = data[offset : offset + width]
        hex_col = " ".join(f"{b:02x}" for b in chunk).ljust(width * 3 - 1)
        ascii_col = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
        lines.append(f"{base_addr + offset:#010x}: {hex_col}  {ascii_col}")
    return "\n".join(lines)
