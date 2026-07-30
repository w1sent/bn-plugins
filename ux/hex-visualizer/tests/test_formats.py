import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formats import detect  # noqa: E402


def test_no_match_on_random_bytes():
    assert detect(b"not a known format, just plain text padding here") is None


def test_empty_data_no_match():
    assert detect(b"") is None


def test_png_signature_and_dimensions():
    ihdr_data = struct.pack(">II", 64, 32) + b"\x08\x06\x00\x00\x00"
    data = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr_data))
        + b"IHDR"
        + ihdr_data
    )
    match = detect(data)
    assert match is not None
    assert match.kind == "png"
    assert match.previewable is True
    assert match.details["width"] == "64"
    assert match.details["height"] == "32"


def test_gif89a():
    data = b"GIF89a" + struct.pack("<HH", 10, 20) + b"\x00" * 3
    match = detect(data)
    assert match.kind == "gif"
    assert match.details == {"width": "10", "height": "20"}


def test_bmp_with_valid_dib_header_size():
    header = bytearray(30)
    header[0:2] = b"BM"
    struct.pack_into("<I", header, 14, 40)  # BITMAPINFOHEADER size
    struct.pack_into("<ii", header, 18, 100, 50)
    match = detect(bytes(header))
    assert match.kind == "bmp"
    assert match.details == {"width": "100", "height": "50"}


def test_bmp_two_letters_alone_is_not_enough():
    # "BM" plus garbage that doesn't match any known DIB header size
    # shouldn't false-positive as a BMP.
    data = b"BM" + b"\xff" * 24
    assert detect(data) is None


def test_ico_icon():
    data = struct.pack("<HHH", 0, 1, 3)
    match = detect(data)
    assert match.kind == "ico"
    assert match.details["image_count"] == "3"


def test_webp():
    data = b"RIFF" + struct.pack("<I", 100) + b"WEBP"
    match = detect(data)
    assert match.kind == "webp"


def test_jpeg_with_sof0_dimensions():
    # SOF0 segment: marker FFC0, length, precision, height, width, ...
    sof_payload = b"\x08" + struct.pack(">HH", 480, 640) + b"\x03"
    sof_segment = b"\xff\xc0" + struct.pack(">H", len(sof_payload) + 2) + sof_payload
    data = b"\xff\xd8\xff" + b"\xe0\x00\x07JFIF\x00" + sof_segment
    match = detect(data)
    assert match.kind == "jpeg"
    assert match.details == {"width": "640", "height": "480"}


def test_jpeg_truncated_before_sof_has_no_dimensions():
    data = b"\xff\xd8\xff\xe0"
    match = detect(data)
    assert match.kind == "jpeg"
    assert match.details == {}


def test_isobmff_mp4_ftyp_box():
    compatible = b"isomiso2avc1mp41"
    box_size = 16 + len(compatible)
    data = (
        struct.pack(">I", box_size)
        + b"ftyp"
        + b"isom"
        + struct.pack(">I", 512)
        + compatible
    )
    match = detect(data)
    assert match.kind == "isobmff"
    assert match.previewable is False
    assert match.details["major_brand"] == "isom"
    assert "avc1" in match.details["compatible_brands"]


def test_detect_returns_first_match_only():
    match = detect(b"GIF89a" + b"\x00" * 20)
    assert match is not None and match.kind == "gif"
