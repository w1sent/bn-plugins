import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formats import carve_extent  # noqa: E402


def _chunked_reader(full_data: bytes, chunk_size: int = 3):
    """A read_more() that only ever hands back `chunk_size` bytes at a
    time (regardless of how much was asked for) -- exercises carvers'
    ability to keep calling read_more rather than assuming one call
    supplies everything."""

    def read_more(offset: int, want: int) -> bytes:
        return full_data[offset : offset + min(want, chunk_size)]

    return read_more


def _make_png(width=2, height=2) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_carve_png_matches_full_length_and_handles_trailing_garbage():
    png = _make_png()
    padded = png + b"\x90" * 32  # simulate trailing bytes after the real file
    length = carve_extent("png", padded[:16], _chunked_reader(padded))
    assert length == len(png)


def test_carve_png_returns_none_when_iend_never_arrives():
    truncated = _make_png()[:20]  # cut off mid-IDAT, no IEND chunk

    def read_more(offset, want):
        return truncated[offset : offset + want]

    assert carve_extent("png", truncated[:16], read_more) is None


def test_carve_bmp_reads_size_directly_from_header():
    header = bytearray(30)
    header[0:2] = b"BM"
    struct.pack_into("<I", header, 2, 12345)  # declared file size
    full = bytes(header) + b"\x00" * 100
    length = carve_extent("bmp", full[:16], _chunked_reader(full))
    assert length == 12345


def test_carve_webp_riff_size_plus_header():
    payload = b"WEBP" + b"VP8 " + struct.pack("<I", 4) + b"\x00\x00\x00\x00"
    riff_size = len(payload)
    full = b"RIFF" + struct.pack("<I", riff_size) + payload
    length = carve_extent("webp", full[:16], _chunked_reader(full))
    assert length == riff_size + 8
    assert length == len(full)


def test_carve_ico_uses_max_directory_entry_extent():
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 16, 16, 0, 0, 1, 32, 500, 22)  # 500 bytes at offset 22
    full = header + entry + b"\x00" * 500
    length = carve_extent("ico", full[:16], _chunked_reader(full))
    assert length == 22 + 500


def test_carve_gif_walks_extension_and_image_blocks_to_trailer():
    header = b"GIF89a" + struct.pack("<HHBBB", 4, 4, 0, 0, 0)  # no global color table
    # graphic control extension: 0x21 0xF9, sub-block len 4, 4 data bytes, terminator
    gce = b"\x21\xf9" + bytes([4]) + b"\x00\x00\x00\x00" + b"\x00"
    # minimal image descriptor + LZW min code size + one data sub-block + terminator
    image_desc = b"\x2c" + struct.pack("<HHHH", 0, 0, 4, 4) + bytes([0])
    image_data = bytes([2]) + b"\x00\x01" + bytes([2]) + b"\x02\x03" + bytes([0])
    trailer = b"\x3b"
    full = header + gce + image_desc + bytes([2]) + image_data + trailer
    length = carve_extent("gif", full[:13], _chunked_reader(full))
    assert length == len(full)


def test_carve_jpeg_skips_stuffed_ff00_in_entropy_data_to_reach_eoi():
    sof_payload = b"\x08" + struct.pack(">HH", 1, 1) + b"\x01\x01\x11\x00"
    sof = b"\xff\xc0" + struct.pack(">H", len(sof_payload) + 2) + sof_payload
    sos_payload = b"\x01\x01\x00\x00\x00"
    sos = b"\xff\xda" + struct.pack(">H", len(sos_payload) + 2) + sos_payload
    # entropy-coded data containing a stuffed 0xFF00 (not a real marker)
    entropy = b"\x11\xff\x00\x22\x33"
    eoi = b"\xff\xd9"
    full = b"\xff\xd8" + sof + sos + entropy + eoi
    length = carve_extent("jpeg", full[:16], _chunked_reader(full))
    assert length == len(full)


def test_carve_isobmff_sums_top_level_boxes():
    ftyp = struct.pack(">I", 16) + b"ftyp" + b"isom" + struct.pack(">I", 0)
    mdat = struct.pack(">I", 12) + b"mdat" + b"\x01\x02\x03\x04"
    full = ftyp + mdat
    length = carve_extent("isobmff", full[:16], _chunked_reader(full))
    assert length == len(full)


def test_carve_unsupported_kind_returns_none():
    assert carve_extent("nope", b"", lambda o, w: b"") is None
