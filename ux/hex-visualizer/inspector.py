"""Fixed common-type interpretation table for the hex-visualizer panel.

Pure stdlib, no `binaryninja`/`binaryninjaui` imports -- same reasoning as
formats.py (see docs/adr/0037): unit-testable headlessly, and this is
deliberately a *fixed* scalar table (int8-64, float32/64, GUID/UUID,
time32_t/time64_t, DOS date/time, binary/hex, string previews) rather than
a user-defined struct/pattern overlay, which is out of scope for v1.
"""

from __future__ import annotations

import struct
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class InspectorRow:
    label: str
    value: str


# (label, struct format code, byte width) -- struct format codes are
# little-endian by default; big-endian rows swap the leading "<" for ">".
_INT_FIELDS = [
    ("int8", "b", 1),
    ("uint8", "B", 1),
    ("int16", "h", 2),
    ("uint16", "H", 2),
    ("int32", "i", 4),
    ("uint32", "I", 4),
    ("int64", "q", 8),
    ("uint64", "Q", 8),
]

_FLOAT_FIELDS = [
    ("float32", "f", 4),
    ("float64", "d", 8),
]


def build_inspection_table(data: bytes) -> list:
    """Decode `data` (the current hex-view selection, or as much of it as
    was read) into a fixed table of scalar interpretations. Rows for
    types wider than `len(data)` are omitted rather than shown as
    truncated/garbage values."""
    rows = []

    for label, code, width in _INT_FIELDS + _FLOAT_FIELDS:
        if len(data) < width:
            continue
        le = struct.unpack_from("<" + code, data, 0)[0]
        be = struct.unpack_from(">" + code, data, 0)[0]
        if isinstance(le, float):
            le_str, be_str = f"{le:g}", f"{be:g}"
        else:
            le_str, be_str = str(le), str(be)
        if width == 1:
            rows.append(InspectorRow(label, le_str))
        else:
            rows.append(InspectorRow(f"{label} LE", le_str))
            rows.append(InspectorRow(f"{label} BE", be_str))

    rows.extend(_guid_uuid_rows(data))
    rows.extend(_time_rows(data))
    dos_row = _dos_datetime_row(data)
    if dos_row is not None:
        rows.append(dos_row)

    rows.append(InspectorRow("hex", data.hex()))
    rows.append(_binary_row(data))
    rows.extend(_string_preview_rows(data))
    return rows


def _guid_uuid_rows(data: bytes) -> list:
    """GUID (Windows/COM mixed-endian octet order) and UUID (RFC 4122
    big-endian octet order) interpretations of the first 16 bytes -- same
    16 bytes, two different conventional orderings of them."""
    if len(data) < 16:
        return []
    raw16 = data[:16]
    return [
        InspectorRow("GUID", "{" + str(uuid.UUID(bytes_le=raw16)) + "}"),
        InspectorRow("UUID", str(uuid.UUID(bytes=raw16))),
    ]


def _time_rows(data: bytes) -> list:
    rows = []
    if len(data) >= 4:
        rows.append(InspectorRow("time32_t LE", _format_unix_timestamp(struct.unpack_from("<i", data, 0)[0])))
        rows.append(InspectorRow("time32_t BE", _format_unix_timestamp(struct.unpack_from(">i", data, 0)[0])))
    if len(data) >= 8:
        rows.append(InspectorRow("time64_t LE", _format_unix_timestamp(struct.unpack_from("<q", data, 0)[0])))
        rows.append(InspectorRow("time64_t BE", _format_unix_timestamp(struct.unpack_from(">q", data, 0)[0])))
    return rows


def _format_unix_timestamp(value: int) -> str:
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return f"{value} (out of range)"


def _dos_datetime_row(data: bytes):
    """MS-DOS packed date/time, as stored in ZIP local file headers and FAT
    directory entries: a 16-bit time field (5/6/5 bits hour/minute/
    half-seconds) followed by a 16-bit date field (7/4/5 bits
    year-since-1980/month/day)."""
    if len(data) < 4:
        return None
    dos_time, dos_date = struct.unpack_from("<HH", data, 0)
    try:
        year = 1980 + (dos_date >> 9)
        month = (dos_date >> 5) & 0x0F
        day = dos_date & 0x1F
        hour = dos_time >> 11
        minute = (dos_time >> 5) & 0x3F
        second = (dos_time & 0x1F) * 2
        text = datetime(year, month, day, hour, minute, second).isoformat()
    except ValueError:
        text = f"(invalid: date={dos_date:#06x} time={dos_time:#06x})"
    return InspectorRow("DOS date/time", text)


def _binary_row(data: bytes) -> InspectorRow:
    return InspectorRow("binary", " ".join(f"{b:08b}" for b in data))


def _string_preview_rows(data: bytes) -> list:
    rows = []

    ascii_str = _decode_printable(data, "ascii")
    if ascii_str:
        rows.append(InspectorRow("ASCII", ascii_str))

    if ascii_str is None:
        utf8_str = _decode_printable(data, "utf-8")
        if utf8_str:
            rows.append(InspectorRow("UTF-8", utf8_str))

    utf16_str = _decode_printable(data, "utf-16-le")
    if utf16_str:
        rows.append(InspectorRow("UTF-16LE", utf16_str))

    return rows


def _decode_printable(data: bytes, encoding: str):
    """Decode `data` up to (not including) the first NUL-terminator/decode
    failure, or None if nothing printable came out. Best-effort preview,
    not a strict validator -- a selection is rarely an exactly-terminated
    string.

    The terminator search is aligned to the encoding's code-unit width (2
    bytes for utf-16-le) rather than a plain `bytes.find` -- an unaligned
    search can match a "\\x00\\x00" that straddles two code units instead
    of a real terminator, cutting the string mid-character and making it
    fail to decode (e.g. "hi\\0" as utf-16-le is 68 00 69 00 00 00; a
    byte-granularity search finds "\\0\\0" at offset 3, splitting the 'i'
    code unit in half)."""
    unit = 2 if encoding == "utf-16-le" else 1
    terminator = b"\x00" * unit
    cut = None
    for i in range(0, len(data) - unit + 1, unit):
        if data[i : i + unit] == terminator:
            cut = i
            break
    raw = data if cut is None else data[:cut]
    if not raw:
        return None
    try:
        text = raw.decode(encoding)
    except (UnicodeDecodeError, ValueError):
        return None
    if not all(c.isprintable() or c in "\t\n\r" for c in text):
        return None
    return text
