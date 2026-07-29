import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hexdump import format_hexdump  # noqa: E402


def test_empty_data_returns_empty_string():
    assert format_hexdump(b"") == ""


def test_single_full_row():
    data = bytes(range(16))
    result = format_hexdump(data, base_addr=0x1000)
    assert result == (
        "0x00001000: 00 01 02 03 04 05 06 07 08 09 0a 0b 0c 0d 0e 0f  " + "." * 16
    )


def test_ascii_printable_bytes_shown_as_chars():
    result = format_hexdump(b"ABCD", base_addr=0)
    assert result.endswith("ABCD")


def test_non_printable_bytes_shown_as_dot():
    result = format_hexdump(bytes([0x00, 0x41, 0x7F, 0xFF]), base_addr=0)
    assert result.endswith(".A..")


def test_partial_last_row_is_padded_and_aligned():
    data = bytes(range(18))  # one full row of 16 + 2 more
    result = format_hexdump(data, base_addr=0)
    lines = result.splitlines()
    assert len(lines) == 2
    # the ASCII column should start at the same offset on both rows
    # regardless of how many bytes the (padded) hex column actually has
    assert lines[0].index("  .") == lines[1].index("  .")


def test_addresses_increment_by_width():
    data = bytes(32)
    result = format_hexdump(data, base_addr=0x2000, width=16)
    lines = result.splitlines()
    assert lines[0].startswith("0x00002000:")
    assert lines[1].startswith("0x00002010:")
