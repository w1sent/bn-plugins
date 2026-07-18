"""Dehydration decoder + pointer-scan fallback.

.NET 8+ NativeAOT binaries compress ("dehydrate") their runtime metadata
with a tiny 6-opcode instruction stream so it doesn't bloat the image; at
startup the runtime re-inflates ("rehydrates") it into a zero-initialized
`hydrated` section. .NET 7 (and .NET 9/10 builds with dehydration disabled)
skip this and just leave plain pointer-laden data in the image, so recovery
falls back to a brute-force aligned pointer scan instead.

Ported from washi1337/ghidra-nativeaot's
nativeaot/rehydration/MetadataRehydratorNet80.java, with the manual
pointer-scan fallback from NativeAotAnalyzer.scanForPointers.
"""

import struct
from dataclasses import dataclass

COPY = 0x00
ZERO_FILL = 0x01
REL_PTR32_RELOC = 0x02
PTR_RELOC = 0x03
INLINE_REL_PTR32_RELOC = 0x04
INLINE_PTR_RELOC = 0x05

_COMMAND_MASK = 0x07
_PAYLOAD_SHIFT = 3
_MAX_RAW_SHORT_PAYLOAD = (1 << (8 - _PAYLOAD_SHIFT)) - 1  # 31
_MAX_EXTRA_PAYLOAD_BYTES = 3
_MAX_SHORT_PAYLOAD = _MAX_RAW_SHORT_PAYLOAD - _MAX_EXTRA_PAYLOAD_BYTES  # 28


@dataclass
class PointerScanResult:
    range_start: int
    range_end: int
    pointer_locations: list


class _Cursor:
    """Byte-stream cursor over a bytes buffer that also tracks the absolute
    address each position corresponds to (buffer[0] == memory[base_addr])."""

    def __init__(self, data, base_addr):
        self.data = data
        self.base_addr = base_addr
        self.pos = 0

    @property
    def address(self):
        return self.base_addr + self.pos

    def read_byte(self):
        b = self.data[self.pos]
        self.pos += 1
        return b

    def read_bytes(self, n):
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return chunk

    def read_int32(self):
        value = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return value

    def eof(self, end_addr):
        return self.address >= end_addr


def _read_command(cursor):
    b = cursor.read_byte()
    command = b & _COMMAND_MASK
    payload = b >> _PAYLOAD_SHIFT
    extra_bytes = payload - _MAX_SHORT_PAYLOAD
    if extra_bytes > 0:
        payload = cursor.read_byte()
        if extra_bytes > 1:
            payload += cursor.read_byte() << 8
            if extra_bytes > 2:
                payload += cursor.read_byte() << 16
        payload += _MAX_SHORT_PAYLOAD
    return command, payload


def _read_rel_ptr32_inline(cursor):
    """Rel32 field embedded in the command stream itself: relative to the
    field's own address."""
    field_addr = cursor.address
    offset = cursor.read_int32()
    return field_addr + offset


def _read_rel_ptr32_at(bv, index):
    """Rel32 field read out of the fixups table at an absolute address,
    without moving the command-stream cursor."""
    raw = bv.read(index, 4)
    if len(raw) < 4:
        raise ValueError(f"could not read fixup rel32 at {index:#x}")
    (offset,) = struct.unpack("<i", raw)
    return index + offset


def _append_rel_ptr32(hydrated, hydration_base, target_addr):
    field_addr = hydration_base + len(hydrated)
    delta = target_addr - field_addr
    hydrated.extend(struct.pack("<i", delta))


_COMMAND_NAMES = {
    COPY: "COPY",
    ZERO_FILL: "ZERO_FILL",
    REL_PTR32_RELOC: "REL_PTR32_RELOC",
    PTR_RELOC: "PTR_RELOC",
    INLINE_REL_PTR32_RELOC: "INLINE_REL_PTR32_RELOC",
    INLINE_PTR_RELOC: "INLINE_PTR_RELOC",
}


def _ensure_writable_backing(bv, start, length):
    """The hydration target is normally a zero-initialized (`.bss`-style)
    segment with no file backing (`data_length == 0`) -- `BinaryView.write`
    silently no-ops there since there's nothing in the parent view to patch.
    Give every such segment overlapping [start, start+length) real backing
    bytes (appended to the raw/parent view) so writes actually land."""

    end = start + length
    addr = start
    while addr < end:
        segment = bv.get_segment_at(addr)
        if segment is None:
            raise ValueError(f"{addr:#x}: no segment covers the hydration target")

        if segment.data_length == 0:
            from binaryninja.enums import SegmentFlag

            flags = SegmentFlag.SegmentContainsData
            if segment.readable:
                flags |= SegmentFlag.SegmentReadable
            if segment.writable:
                flags |= SegmentFlag.SegmentWritable
            if segment.executable:
                flags |= SegmentFlag.SegmentExecutable

            raw = bv.parent_view or bv
            new_offset = raw.end
            raw.insert(new_offset, b"\x00" * segment.length)
            bv.add_user_segment(segment.start, segment.length, new_offset, segment.length, flags)

        addr = segment.end


def rehydrate(bv, dehydrated_start, dehydrated_end, on_progress=None, annotate=False):
    """Decode the dehydrated data command stream at
    [dehydrated_start, dehydrated_end) and materialize the hydrated bytes
    into the binary view at the hydration base address the stream itself
    specifies (its first 4 bytes are a rel32 pointer to it).

    `annotate=True` leaves an EOL comment at each opcode's address naming
    it (Ghidra's "Markup rehydration code" analyzer option) -- off by
    default since it's purely a code-reading aid for the compressed stream
    itself, not something later analysis depends on."""

    raw = bv.read(dehydrated_start, dehydrated_end - dehydrated_start)
    if len(raw) < dehydrated_end - dehydrated_start:
        raise ValueError("could not read full dehydrated data section")

    cursor = _Cursor(raw, dehydrated_start)
    hydration_base = _read_rel_ptr32_inline(cursor)

    fixups_start = dehydrated_end

    hydrated = bytearray()
    pointer_locations = []

    total = dehydrated_end - dehydrated_start
    while cursor.address < dehydrated_end:
        if on_progress:
            on_progress(cursor.address - dehydrated_start, total)

        command_addr = cursor.address
        command, payload = _read_command(cursor)

        if annotate:
            try:
                bv.set_comment_at(command_addr, f"{_COMMAND_NAMES.get(command, '?')} {payload:#x}")
            except Exception:
                pass

        if command == COPY:
            hydrated.extend(cursor.read_bytes(payload))

        elif command == ZERO_FILL:
            hydrated.extend(b"\x00" * payload)

        elif command == REL_PTR32_RELOC:
            target = _read_rel_ptr32_at(bv, fixups_start + payload * 4)
            _append_rel_ptr32(hydrated, hydration_base, target)

        elif command == PTR_RELOC:
            target = _read_rel_ptr32_at(bv, fixups_start + payload * 4)
            pointer_locations.append(hydration_base + len(hydrated))
            hydrated.extend(struct.pack("<Q", target & 0xFFFFFFFFFFFFFFFF))

        elif command == INLINE_REL_PTR32_RELOC:
            for _ in range(payload):
                target = _read_rel_ptr32_inline(cursor)
                _append_rel_ptr32(hydrated, hydration_base, target)

        elif command == INLINE_PTR_RELOC:
            for _ in range(payload):
                target = _read_rel_ptr32_inline(cursor)
                pointer_locations.append(hydration_base + len(hydrated))
                hydrated.extend(struct.pack("<Q", target & 0xFFFFFFFFFFFFFFFF))

        else:
            raise ValueError(f"{cursor.address:#x}: unknown dehydration opcode {command}")

    _ensure_writable_backing(bv, hydration_base, len(hydrated))
    written = bv.write(hydration_base, bytes(hydrated))
    if written != len(hydrated):
        raise ValueError(
            f"only wrote {written}/{len(hydrated)} bytes of hydrated data at "
            f"{hydration_base:#x} -- is that address inside a writable segment?"
        )

    return PointerScanResult(hydration_base, hydration_base + len(hydrated), pointer_locations)


def scan_for_pointers(bv, on_progress=None):
    """.NET 7 / dehydration-disabled fallback: brute-force scan every
    initialized, non-executable segment for 8-byte-aligned values that look
    like pointers into the loaded image."""

    segments = [s for s in bv.segments if s.readable and not s.executable and s.data_length > 0]
    if not segments:
        return PointerScanResult(bv.start, bv.end, [])

    range_start = min(s.start for s in segments)
    range_end = max(s.start + s.length for s in segments)

    pointers = []
    total = sum(s.data_length for s in segments)
    done = 0

    for segment in segments:
        start = segment.start
        if start % 8 != 0:
            start += 8 - (start % 8)
        end = segment.start + segment.data_length

        addr = start
        while addr + 8 <= end:
            if on_progress:
                on_progress(done, total)
                done += 8

            raw = bv.read(addr, 8)
            if len(raw) == 8:
                (value,) = struct.unpack("<Q", raw)
                if bv.get_segment_at(value) is not None:
                    pointers.append(addr)

            addr += 8

    return PointerScanResult(range_start, range_end, pointers)
