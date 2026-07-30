"""Tests api.inspect's carve-wiring logic directly, without importing the
`hex-visualizer` package (its __init__.py needs `core/`, only present in
an installed tree -- see docs/adr/0037's formats.py note). api.py itself
has no Qt/binaryninjaui dependency, so it's loaded as a standalone module
with a stub `core.logging` substituted in, and exercised against a fake
`bv` stand-in rather than a real BinaryView."""

import struct
import sys
import types
import zlib
from pathlib import Path

_PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PLUGIN_DIR))

import formats  # noqa: E402
import inspector  # noqa: E402

# api.py does `from .core.logging import get_logger` -- stub out a fake
# `hex_visualizer_api_test_pkg.core.logging` so api.py can be loaded as a
# real submodule (relative imports need a package) without needing the
# actual vendored core/ this dev checkout doesn't have.
import importlib.util
import logging as _logging

_pkg_name = "_hex_visualizer_api_test_pkg"
_pkg = types.ModuleType(_pkg_name)
_pkg.__path__ = [str(_PLUGIN_DIR)]
sys.modules[_pkg_name] = _pkg

_core_pkg = types.ModuleType(f"{_pkg_name}.core")
_core_pkg.__path__ = []
sys.modules[f"{_pkg_name}.core"] = _core_pkg

_core_logging = types.ModuleType(f"{_pkg_name}.core.logging")
_core_logging.get_logger = lambda name, level="INFO": _logging.getLogger(name)
sys.modules[f"{_pkg_name}.core.logging"] = _core_logging

sys.modules[f"{_pkg_name}.formats"] = formats
sys.modules[f"{_pkg_name}.inspector"] = inspector

_api_spec = importlib.util.spec_from_file_location(f"{_pkg_name}.api", _PLUGIN_DIR / "api.py")
api = importlib.util.module_from_spec(_api_spec)
api.__package__ = _pkg_name
sys.modules[f"{_pkg_name}.api"] = api
_api_spec.loader.exec_module(api)


class _FakeBV:
    """Minimal bv.read() stand-in over a flat byte buffer at address 0."""

    def __init__(self, data: bytes):
        self.data = data

    def read(self, addr: int, length: int) -> bytes:
        return self.data[addr : addr + length]


def _make_png(width=2, height=2) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_inspect_carves_full_png_even_when_selection_is_short():
    png = _make_png()
    bv = _FakeBV(png + b"\x90" * 64)  # trailing garbage after the real file
    result = api.inspect(bv, 0, 1)  # user selected just 1 byte
    assert result.format_match is not None
    assert result.format_match.kind == "png"
    assert result.carved_length == len(png)
    assert result.data == png  # preview got the *full* carved file, not 1 byte


def test_inspect_table_rows_reflect_literal_selection_not_the_carve():
    png = _make_png()
    bv = _FakeBV(png + b"\x90" * 64)
    result = api.inspect(bv, 0, 1)
    row_map = {r.label: r.value for r in result.rows}
    # 1-byte selection -> only int8/uint8/hex/binary rows, not carved-file-sized ones
    assert row_map["int8"] == str(struct.unpack("b", png[0:1])[0])
    assert "int16 LE" not in row_map


def test_inspect_no_format_match_falls_back_to_raw_sniff_window():
    bv = _FakeBV(b"not a media file" * 10)
    result = api.inspect(bv, 0, 8)
    assert result.format_match is None
    assert result.carved_length is None
    assert result.data == bv.data[:8]


def test_inspect_zero_length_selection():
    bv = _FakeBV(b"\x89PNG\r\n\x1a\n")
    result = api.inspect(bv, 0, 0)
    assert result.format_match is None
    assert result.rows and result.rows[0].label == "hex"
    assert result.data == b""


def test_inspect_carve_truncation_reported():
    # Patches api.CARVE_MAX (bounds how much preview data api.inspect
    # reads once a carve succeeds), not formats.CARVE_MAX (bounds the
    # carve *parse* itself) -- the parse must stay unbounded here so
    # carve_extent can actually determine the PNG's true 73-byte length
    # before api.py separately caps how much of it gets read for preview.
    png = _make_png()
    bv = _FakeBV(png)
    original_max = api.CARVE_MAX
    api.CARVE_MAX = 20
    try:
        result = api.inspect(bv, 0, 1)
        assert result.carve_truncated is True
        assert len(result.data) == 20
        assert result.carved_length == len(png)
    finally:
        api.CARVE_MAX = original_max
