import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inspector import build_inspection_table  # noqa: E402


def _row_map(rows):
    return {row.label: row.value for row in rows}


def test_single_byte_only_gets_int8_rows():
    rows = _row_map(build_inspection_table(b"\x2a"))
    assert rows["int8"] == "42"
    assert rows["uint8"] == "42"
    assert "int16 LE" not in rows


def test_negative_int8():
    rows = _row_map(build_inspection_table(b"\xff"))
    assert rows["int8"] == "-1"
    assert rows["uint8"] == "255"


def test_int32_endianness():
    data = struct.pack("<i", 0x01020304)
    rows = _row_map(build_inspection_table(data))
    assert rows["int32 LE"] == "16909060"
    assert rows["int32 BE"] == str(struct.unpack(">i", data)[0])


def test_float32_le():
    data = struct.pack("<f", 3.5)
    rows = _row_map(build_inspection_table(data))
    assert rows["float32 LE"] == "3.5"


def test_wide_types_omitted_when_too_short():
    rows = _row_map(build_inspection_table(b"\x01\x02\x03"))
    assert "int32 LE" not in rows
    assert "int64 LE" not in rows
    assert "float64 LE" not in rows
    assert "int16 LE" in rows


def test_hex_row_always_present():
    rows = _row_map(build_inspection_table(b"\xde\xad\xbe\xef"))
    assert rows["hex"] == "deadbeef"


def test_ascii_string_preview_stops_at_nul():
    data = b"hello\x00garbage"
    rows = _row_map(build_inspection_table(data))
    assert rows["ASCII"] == "hello"


def test_ascii_preview_absent_for_binary_data():
    rows = _row_map(build_inspection_table(b"\x00\x01\x02\x03"))
    assert "ASCII" not in rows


def test_utf16le_string_preview():
    data = "hi".encode("utf-16-le") + b"\x00\x00"
    rows = _row_map(build_inspection_table(data))
    assert rows["UTF-16LE"] == "hi"


def test_empty_data_yields_only_hex_and_binary_rows():
    rows = build_inspection_table(b"")
    assert [r.label for r in rows] == ["hex", "binary"]
    assert rows[0].value == ""
    assert rows[1].value == ""


def test_binary_row():
    rows = _row_map(build_inspection_table(b"\xa5\x01"))
    assert rows["binary"] == "10100101 00000001"


def test_guid_and_uuid_rows_need_16_bytes():
    rows = _row_map(build_inspection_table(b"\x00" * 15))
    assert "GUID" not in rows
    assert "UUID" not in rows


def test_guid_uuid_mixed_vs_big_endian_octet_order():
    # RFC 4122 example UUID 00112233-4455-6677-8899-aabbccddeeff.
    raw = bytes.fromhex("00112233445566778899aabbccddeeff")[:16]
    rows = _row_map(build_inspection_table(raw))
    assert rows["UUID"] == "00112233-4455-6677-8899-aabbccddeeff"
    # GUID reads the first three fields little-endian (Windows/COM
    # convention), so the first 4+2+2 bytes reverse within their fields.
    assert rows["GUID"] == "{33221100-5544-7766-8899-aabbccddeeff}"


def test_time32_t_epoch():
    data = struct.pack("<i", 0) + b"\x00" * 4  # exactly epoch, LE
    rows = _row_map(build_inspection_table(data))
    assert rows["time32_t LE"] == "1970-01-01T00:00:00+00:00"


def test_time32_t_negative_predates_epoch_without_crashing():
    data = struct.pack("<i", -1) + b"\x00" * 4
    rows = _row_map(build_inspection_table(data))
    assert rows["time32_t LE"] == "1969-12-31T23:59:59+00:00"


def test_time64_t_needs_8_bytes():
    rows = _row_map(build_inspection_table(b"\x00" * 7))
    assert "time64_t LE" not in rows
    rows = _row_map(build_inspection_table(b"\x00" * 8))
    assert rows["time64_t LE"] == "1970-01-01T00:00:00+00:00"


def test_dos_datetime_round_trip():
    # 2023-06-15 14:23:06 -- seconds truncated to even (DOS stores /2).
    dos_date = ((2023 - 1980) << 9) | (6 << 5) | 15
    dos_time = (14 << 11) | (23 << 5) | (6 // 2)
    data = struct.pack("<HH", dos_time, dos_date)
    rows = _row_map(build_inspection_table(data))
    assert rows["DOS date/time"] == "2023-06-15T14:23:06"


def test_dos_datetime_invalid_reports_instead_of_crashing():
    data = struct.pack("<HH", 0, 0)  # day=0, month=0 -- not a valid date
    rows = _row_map(build_inspection_table(data))
    assert "invalid" in rows["DOS date/time"]
