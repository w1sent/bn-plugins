"""ReadyToRun (RTR) directory parsing and module-header discovery.

NativeAOT binaries retain a stripped-down ReadyToRun directory (signature
`RTR\\0`) even though there is no JIT/IL left -- it is repurposed to point at
the dehydrated metadata blob and the frozen object segment. See
https://blog.washi.dev/posts/recovering-nativeaot-metadata/ and the upstream
ports this module is translated from: washi1337/ghidra-nativeaot
(nativeaot/rtr/*.java) and its IDA port (ida-nativeaot.py).
"""

import struct
from dataclasses import dataclass

RTR_SIGNATURE = 0x00525452  # "RTR\0"

SECTION_FROZEN_OBJECT_REGION = 206  # 0xCE
SECTION_DEHYDRATED_DATA = 207  # 0xCF

_EXPECTED_ENTRY_SIZE = 0x18
_EXPECTED_ENTRY_TYPE = 0x01
_EXPECTED_SECTION_COUNT_UPPER_BOUND = 0x50

HEADER_SYMBOL_NAME = "__ReadyToRunHeader"
MODULES_START_SYMBOL_NAME = "__modules_a"
MODULES_END_SYMBOL_NAME = "__modules_z"
DEHYDRATED_DATA_SYMBOL_NAME = "__dehydrated_data"
HYDRATED_DATA_SYMBOL_NAME = "__hydrated_data"
FROZEN_SEGMENT_START_SYMBOL_NAME = "__FrozenSegmentStart"


@dataclass
class ReadyToRunSection:
    type: int
    flags: int
    start: int
    end: int

    def pointers_in_section(self, addresses):
        return [a for a in addresses if self.start <= a < self.end]


@dataclass
class ReadyToRunDirectory:
    address: int
    major_version: int
    minor_version: int
    attributes: int
    sections: list

    def section_by_type(self, section_type):
        for section in self.sections:
            if section.type == section_type:
                return section
        return None

    @property
    def size(self):
        return 16 + len(self.sections) * 24

    @classmethod
    def read_at(cls, bv, address):
        header = bv.read(address, 16)
        if len(header) < 16:
            raise ValueError(f"could not read RTR header at {address:#x}")

        signature, major, minor, attributes, section_count, entry_size, entry_type = (
            struct.unpack("<IHHIHBB", header)
        )
        if signature != RTR_SIGNATURE:
            raise ValueError(f"no RTR\\0 signature at {address:#x}")
        if section_count > _EXPECTED_SECTION_COUNT_UPPER_BOUND:
            raise ValueError(f"unexpected number of sections {section_count}")

        sections = []
        cursor = address + 16
        for _ in range(section_count):
            raw = bv.read(cursor, 24)
            if len(raw) < 24:
                raise ValueError(f"truncated RTR section table at {cursor:#x}")
            s_type, s_flags, s_start, s_end = struct.unpack("<IIQQ", raw)
            sections.append(ReadyToRunSection(s_type, s_flags, s_start, s_end))
            cursor += 24

        return cls(address, major, minor, attributes, sections)


def _is_likely_valid_rtr_header(bv, address):
    header = bv.read(address, 16)
    if len(header) < 16:
        return False
    signature, _major, _minor, _attrs, section_count, entry_size, entry_type = (
        struct.unpack("<IHHIHBB", header)
    )
    return (
        signature == RTR_SIGNATURE
        and section_count < _EXPECTED_SECTION_COUNT_UPPER_BOUND
        and entry_size == _EXPECTED_ENTRY_SIZE
        and entry_type == _EXPECTED_ENTRY_TYPE
    )


def _data_segments(bv):
    for segment in bv.segments:
        if segment.readable and not segment.executable and segment.data_length > 0:
            yield segment


def locate_via_symbols(bv):
    """Look for an already-labelled RTR header, or the __modules_a/__modules_z
    array of module header pointers (the second argument passed to
    StartupCodeHelpers.InitializeModules in the native entry point)."""
    candidates = []

    for sym in bv.get_symbols_by_name(HEADER_SYMBOL_NAME):
        candidates.append(sym.address)

    starts = bv.get_symbols_by_name(MODULES_START_SYMBOL_NAME)
    ends = bv.get_symbols_by_name(MODULES_END_SYMBOL_NAME)
    if not starts or not ends:
        return [a for a in candidates if _is_likely_valid_rtr_header(bv, a)]

    start = starts[0].address
    end = ends[0].address
    count = (end - start) // 8
    for i in range(count):
        raw = bv.read(start + i * 8, 8)
        if len(raw) < 8:
            continue
        (value,) = struct.unpack("<Q", raw)
        if value == 0:
            continue
        if value not in candidates:
            candidates.append(value)

    return [a for a in candidates if _is_likely_valid_rtr_header(bv, a)]


def locate_via_signature(bv):
    """Fallback: scan every non-executable, initialized (data-backed) segment
    for 8-byte-aligned RTR header signatures."""
    result = []
    for segment in _data_segments(bv):
        start = segment.start
        if start % 8 != 0:
            start += 8 - (start % 8)
        end = segment.start + segment.data_length

        addr = start
        while addr + 16 <= end:
            if _is_likely_valid_rtr_header(bv, addr):
                result.append(addr)
            addr += 8

    return result


def locate_modules(bv):
    """Symbol-based locator first (cheap, precise), signature scan as fallback."""
    candidates = locate_via_symbols(bv)
    if candidates:
        return candidates
    return locate_via_signature(bv)
