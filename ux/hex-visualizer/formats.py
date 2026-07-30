"""Byte-content format sniffing for the hex-visualizer inspector panel.

Pure stdlib, no `binaryninja`/`binaryninjaui` imports -- the selection is
an arbitrary byte range with no filename or BN type to key off, so
detection is magic-byte/structure sniffing only. Kept import-free of the
UI stack so it's unit-testable headlessly (see docs/adr/0037).

`detect()` is deliberately a single best-guess match, not a list of
candidates -- the panel shows one preview at a time, so ambiguity between
formats isn't a case the caller needs to handle.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FormatMatch:
    kind: str  # short machine-readable tag, e.g. "png", "isobmff"
    label: str  # human-readable format name for the panel header
    previewable: bool  # True if Qt's QImage can decode this directly
    details: dict = field(default_factory=dict)  # e.g. {"width": "64", "height": "64"}


def detect(data: bytes) -> Optional[FormatMatch]:
    for sniffer in (
        _sniff_png,
        _sniff_gif,
        _sniff_bmp,
        _sniff_ico,
        _sniff_webp,
        _sniff_jpeg,
        _sniff_isobmff,
    ):
        match = sniffer(data)
        if match is not None:
            return match
    return None


# Bounds how far a carve will read beyond the initial sniff window --
# corrupt/adversarial length fields shouldn't turn a preview into an
# unbounded read of the whole binary.
CARVE_MAX = 16 * 1024 * 1024  # 16 MiB


class _ByteSource:
    """Growable view over `prefix`, fetching more via `read_more(offset,
    length)` on demand as a carver's cursor walks past what's already
    buffered. `offset` passed to `read_more` is relative to the start of
    `prefix` (i.e. the same origin the caller's `start` address maps to)."""

    def __init__(self, prefix: bytes, read_more):
        self._buf = bytearray(prefix)
        self._read_more = read_more

    def ensure(self, end: int) -> bool:
        # Loops rather than trusting one read_more() call to satisfy the
        # whole request -- a real bv.read() (like this test double) can
        # legitimately hand back fewer bytes than asked for.
        while len(self._buf) < end:
            if end > CARVE_MAX:
                return False
            chunk = self._read_more(len(self._buf), end - len(self._buf))
            if not chunk:
                return False
            self._buf.extend(chunk)
        return True

    def byte_at(self, pos: int) -> int:
        return self._buf[pos]

    def __getitem__(self, key):
        return bytes(self._buf[key])


def carve_extent(kind: str, prefix: bytes, read_more) -> Optional[int]:
    """Given a format already matched (via `detect`) at the start of
    `prefix`, walk its container structure to find the full byte length of
    the embedded file -- reading more via `read_more(offset, length)` as
    needed, bounded by CARVE_MAX. Returns None if the extent can't be
    determined (unsupported format, or the structure didn't parse)."""
    carver = _CARVERS.get(kind)
    if carver is None:
        return None
    try:
        return carver(_ByteSource(prefix, read_more))
    except (struct.error, IndexError):
        return None


def _carve_png(src: _ByteSource) -> Optional[int]:
    pos = 8  # past the 8-byte signature
    while True:
        if not src.ensure(pos + 8):
            return None
        length = struct.unpack(">I", src[pos : pos + 4])[0]
        chunk_type = src[pos + 4 : pos + 8]
        chunk_end = pos + 8 + length + 4  # length field + type + data + crc32
        if not src.ensure(chunk_end):
            return None
        if chunk_type == b"IEND":
            return chunk_end
        pos = chunk_end


def _carve_gif(src: _ByteSource) -> Optional[int]:
    if not src.ensure(13):
        return None
    packed = src.byte_at(10)
    pos = 13
    if packed & 0x80:
        pos += 3 * (2 ** ((packed & 0x07) + 1))  # global color table

    while True:
        if not src.ensure(pos + 1):
            return None
        marker = src.byte_at(pos)
        if marker == 0x3B:  # trailer
            return pos + 1
        if marker == 0x21:  # extension block: introducer + label + sub-blocks
            pos = _gif_skip_sub_blocks(src, pos + 2)
        elif marker == 0x2C:  # image descriptor
            if not src.ensure(pos + 10):
                return None
            local_packed = src.byte_at(pos + 9)
            pos += 10
            if local_packed & 0x80:
                pos += 3 * (2 ** ((local_packed & 0x07) + 1))  # local color table
            pos += 1  # LZW minimum code size
            pos = _gif_skip_sub_blocks(src, pos)
        else:
            return None  # unrecognized block -- bail rather than guess
        if pos is None:
            return None


def _gif_skip_sub_blocks(src: _ByteSource, pos: int) -> Optional[int]:
    while True:
        if not src.ensure(pos + 1):
            return None
        size = src.byte_at(pos)
        pos += 1
        if size == 0:
            return pos
        if not src.ensure(pos + size):
            return None
        pos += size


def _carve_bmp(src: _ByteSource) -> Optional[int]:
    if not src.ensure(6):
        return None
    return struct.unpack("<I", src[2:6])[0]  # file size, given directly in the header


def _carve_ico(src: _ByteSource) -> Optional[int]:
    if not src.ensure(6):
        return None
    count = struct.unpack("<H", src[4:6])[0]
    directory_end = 6 + count * 16
    if not src.ensure(directory_end):
        return None
    extent = directory_end
    for i in range(count):
        entry_off = 6 + i * 16
        size, offset = struct.unpack("<II", src[entry_off + 8 : entry_off + 16])
        extent = max(extent, offset + size)
    return extent


def _carve_webp(src: _ByteSource) -> Optional[int]:
    if not src.ensure(8):
        return None
    riff_size = struct.unpack("<I", src[4:8])[0]
    return riff_size + 8  # RIFF size excludes the 8-byte "RIFF"+size header itself


def _carve_jpeg(src: _ByteSource) -> Optional[int]:
    pos = 2  # past SOI
    while True:
        if not src.ensure(pos + 2):
            return None
        if src.byte_at(pos) != 0xFF:
            return None
        marker = src.byte_at(pos + 1)
        if marker == 0xD9:  # EOI
            return pos + 2
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if not src.ensure(pos + 4):
            return None
        seg_len = struct.unpack(">H", src[pos + 2 : pos + 4])[0]
        seg_end = pos + 2 + seg_len
        if marker != 0xDA:  # not SOS -- an ordinary length-prefixed segment
            if not src.ensure(seg_end):
                return None
            pos = seg_end
            continue
        # SOS: header is length-prefixed, but the entropy-coded scan data
        # after it isn't -- scan byte-by-byte for the next real marker,
        # skipping 0xFF00 byte-stuffing and restart markers (0xD0-0xD7).
        if not src.ensure(seg_end):
            return None
        pos = seg_end
        while True:
            if not src.ensure(pos + 2):
                return None
            if src.byte_at(pos) == 0xFF:
                nxt = src.byte_at(pos + 1)
                if nxt != 0x00 and not (0xD0 <= nxt <= 0xD7):
                    break  # real marker -- resume the outer loop here
            pos += 1


def _carve_isobmff(src: _ByteSource) -> Optional[int]:
    pos = 0
    while True:
        if not src.ensure(pos + 8):
            return pos or None
        box_size = struct.unpack(">I", src[pos : pos + 4])[0]
        header_len = 8
        if box_size == 1:
            if not src.ensure(pos + 16):
                return pos or None
            box_size = struct.unpack(">Q", src[pos + 8 : pos + 16])[0]
            header_len = 16
        elif box_size == 0:
            return None  # box extends to end-of-file -- extent unknowable structurally
        if box_size < header_len:
            return pos or None
        next_pos = pos + box_size
        if not src.ensure(next_pos):
            return pos or None  # stop at the last box we could fully read
        pos = next_pos


_CARVERS = {
    "png": _carve_png,
    "gif": _carve_gif,
    "bmp": _carve_bmp,
    "ico": _carve_ico,
    "webp": _carve_webp,
    "jpeg": _carve_jpeg,
    "isobmff": _carve_isobmff,
}


def _sniff_png(data: bytes) -> Optional[FormatMatch]:
    sig = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(sig):
        return None
    details = {}
    # IHDR is always the first chunk, immediately after the signature:
    # 4-byte length, 4-byte type "IHDR", then width/height as u32 BE.
    if len(data) >= len(sig) + 8 + 8 and data[len(sig) + 4 : len(sig) + 8] == b"IHDR":
        width, height = struct.unpack_from(">II", data, len(sig) + 8)
        details = {"width": str(width), "height": str(height)}
    return FormatMatch("png", "PNG image", True, details)


def _sniff_gif(data: bytes) -> Optional[FormatMatch]:
    if not (data.startswith(b"GIF87a") or data.startswith(b"GIF89a")):
        return None
    details = {}
    if len(data) >= 10:
        width, height = struct.unpack_from("<HH", data, 6)
        details = {"width": str(width), "height": str(height)}
    return FormatMatch("gif", f"GIF image ({data[3:6].decode('ascii')})", True, details)


def _sniff_bmp(data: bytes) -> Optional[FormatMatch]:
    if not data.startswith(b"BM") or len(data) < 26:
        return None
    # DIB header size at offset 14 -- sanity-check against known header
    # sizes rather than trusting "BM" alone, which two ASCII bytes could
    # coincide with by chance in unrelated data.
    dib_header_size = struct.unpack_from("<I", data, 14)[0]
    if dib_header_size not in (12, 40, 52, 56, 64, 108, 124):
        return None
    details = {}
    if dib_header_size == 12:
        width, height = struct.unpack_from("<HH", data, 18)
    else:
        width, height = struct.unpack_from("<ii", data, 18)
        height = abs(height)
    details = {"width": str(width), "height": str(height)}
    return FormatMatch("bmp", "BMP image", True, details)


def _sniff_ico(data: bytes) -> Optional[FormatMatch]:
    if len(data) < 6:
        return None
    reserved, image_type, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or image_type not in (1, 2) or count == 0:
        return None
    kind_label = "ICO icon" if image_type == 1 else "CUR cursor"
    return FormatMatch("ico", kind_label, True, {"image_count": str(count)})


def _sniff_webp(data: bytes) -> Optional[FormatMatch]:
    if len(data) < 12 or not (data.startswith(b"RIFF") and data[8:12] == b"WEBP"):
        return None
    return FormatMatch("webp", "WebP image", True, {})


def _sniff_jpeg(data: bytes) -> Optional[FormatMatch]:
    if not data.startswith(b"\xff\xd8\xff"):
        return None
    details = {}
    dims = _jpeg_dimensions(data)
    if dims is not None:
        details = {"width": str(dims[0]), "height": str(dims[1])}
    return FormatMatch("jpeg", "JPEG image", True, details)


# SOF (start-of-frame) markers that carry width/height; excludes DHT
# (0xC4), JPG (0xC8), and DAC (0xCC), which share the 0xC0-0xCF range but
# aren't frame headers.
_JPEG_SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg_dimensions(data: bytes) -> Optional[tuple]:
    """Walk JPEG markers looking for a SOFn segment. Best-effort: a
    selection may be truncated before any SOF marker appears, in which
    case this returns None and the caller just omits width/height."""
    pos = 2  # past the initial 0xFFD8
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if pos + 4 > len(data):
            break
        seg_len = struct.unpack_from(">H", data, pos + 2)[0]
        if marker in _JPEG_SOF_MARKERS:
            if pos + 9 > len(data):
                return None
            height, width = struct.unpack_from(">HH", data, pos + 5)
            return (width, height)
        pos += 2 + seg_len
    return None


def _sniff_isobmff(data: bytes) -> Optional[FormatMatch]:
    """ISO-BMFF container (MP4/MOV/M4A/...): first box is `ftyp` with a
    u32-BE size at offset 0 and the 4-byte type at offset 4. Metadata
    only -- no frame/thumbnail decode, see docs/adr/0037."""
    if len(data) < 16 or data[4:8] != b"ftyp":
        return None
    box_size = struct.unpack_from(">I", data, 0)[0]
    major_brand = data[8:12].decode("ascii", errors="replace")
    minor_version = struct.unpack_from(">I", data, 12)[0]
    compatible = []
    pos = 16
    end = min(box_size, len(data)) if box_size >= 16 else len(data)
    while pos + 4 <= end:
        compatible.append(data[pos : pos + 4].decode("ascii", errors="replace"))
        pos += 4
    details = {
        "major_brand": major_brand,
        "minor_version": str(minor_version),
        "compatible_brands": ", ".join(compatible) if compatible else "(none in selection)",
    }
    return FormatMatch("isobmff", f"ISO-BMFF container ({major_brand})", False, details)
