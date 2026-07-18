"""NativeAOT object model: MethodTable/EEType parsing and type-hierarchy
discovery.

Ported from washi1337/ghidra-nativeaot's nativeaot/objectmodel/* (and its
net70/net80 subpackages) and cross-checked against the IDA port
(ida-nativeaot.py). See
https://blog.washi.dev/posts/recovering-nativeaot-metadata/ for the
narrative write-up this algorithm comes from.

A MethodTable (MT) is NativeAOT's runtime type descriptor -- structurally a
C++-style vtable with extra header fields (flags, base size, base-type
pointer, interface pointer array). The RTR major version picks between two
wire layouts:

  net70 (RTR major version <= 8): componentSize:u16, flags:u16, baseSize:u32
  net80 (RTR major version >  8): flags:u32, baseSize:u32

...followed by an identical tail in both: relatedType:ptr64,
numVtableSlots:u16, numInterfaces:u16, hashCode:u32, vtable[u16 count]:ptr64,
interfaces[u16 count]:ptr64. Both header shapes are 24 bytes.

Discovery has no metadata table to enumerate types from -- it works
backwards from System.Object's very distinctive vtable shape (3 slots:
ToString/Equals/GetHashCode, no base type, no interfaces) and then walks the
induced inheritance graph outward: any pointer that dereferences to an
already-known MT is assumed to be another MT's `relatedType` (base type)
field, which lets a new MT be carved out 8 bytes before it. This repeats to
a fixed point.
"""

import struct

NET70 = "net70"
NET80 = "net80"

_HEADER_SIZE = 24  # bytes, both layouts
_RELATED_TYPE_OFFSET = 0x08  # offset of the relatedType field within an MT
_MAX_SLOT_COUNT = 1000
_MAX_PASSES = 100

OBJECT_METHOD_NAMES = ("ToString", "Equals", "GetHashCode")


class ElementType:
    UNKNOWN = 0x00
    VOID = 0x01
    BOOLEAN = 0x02
    CHAR = 0x03
    SBYTE = 0x04
    BYTE = 0x05
    INT16 = 0x06
    UINT16 = 0x07
    INT32 = 0x08
    UINT32 = 0x09
    INT64 = 0x0A
    UINT64 = 0x0B
    INTPTR = 0x0C
    UINTPTR = 0x0D
    SINGLE = 0x0E
    DOUBLE = 0x0F

    VALUETYPE = 0x10
    NULLABLE = 0x12

    CLASS = 0x14
    INTERFACE = 0x15

    SYSTEM_ARRAY = 0x16

    ARRAY = 0x17
    SZARRAY = 0x18
    BYREF = 0x19
    POINTER = 0x1A
    FUNCTION_POINTER = 0x1B

    _PRIMITIVE_NAMES = {
        BOOLEAN: "Boolean",
        CHAR: "Char",
        SBYTE: "Sbyte",
        BYTE: "Byte",
        INT16: "Int16",
        UINT16: "Uint16",
        INT32: "Int32",
        UINT32: "Uint32",
        INT64: "Int64",
        UINT64: "Uint64",
        INTPTR: "IntPtr",
        UINTPTR: "UIntPtr",
        SINGLE: "Single",
        DOUBLE: "Double",
    }

    @staticmethod
    def is_value_type(element_type):
        return ElementType.VOID <= element_type <= ElementType.VALUETYPE

    @staticmethod
    def is_primitive(element_type):
        return ElementType.VOID <= element_type <= ElementType.DOUBLE

    @staticmethod
    def is_array_instance(element_type):
        return element_type in (ElementType.ARRAY, ElementType.SZARRAY)


class MethodTable:
    def __init__(self, address, version):
        self.address = address
        self.version = version
        self.flags = 0
        self.component_size = 0
        self.base_size = 0
        self.related_type_address = 0
        self.hash_code = 0
        self.vtable = []
        self.interface_addresses = []

        self.name = None
        self.related_type = None
        self.interfaces = []
        self.derived_types = set()

    @property
    def element_type(self):
        if self.version == NET70:
            return (self.flags & 0xF800) >> 11
        return (self.flags & 0x7C000000) >> 26

    @property
    def is_class(self):
        return self.element_type == ElementType.CLASS

    @property
    def is_struct(self):
        return self.element_type == ElementType.VALUETYPE

    @property
    def is_interface(self):
        return self.element_type == ElementType.INTERFACE

    @property
    def is_szarray(self):
        return self.element_type == ElementType.SZARRAY

    @property
    def is_value_type(self):
        return ElementType.is_value_type(self.element_type)

    @property
    def is_array_instance(self):
        return ElementType.is_array_instance(self.element_type)

    @property
    def data_size(self):
        return self.base_size - 0x8 - 0x8  # object header + mt pointer

    @property
    def total_size(self):
        return _HEADER_SIZE + 8 * (len(self.vtable) + len(self.interface_addresses))

    def default_name(self):
        et = self.element_type
        addr = f"0x{self.address:x}"
        if et == ElementType.CLASS:
            return f"Class_{addr}"
        if et == ElementType.VALUETYPE:
            return f"Struct_{addr}"
        if et == ElementType.NULLABLE:
            return f"Nullable_{addr}"
        if et == ElementType.INTERFACE:
            return f"IInterface_{addr}"
        if et == ElementType.ARRAY:
            return f"Array_{addr}"
        if et == ElementType.SZARRAY:
            return f"SzArray_{addr}"
        prim = ElementType._PRIMITIVE_NAMES.get(et)
        if prim:
            return f"Enum_{prim}_{addr}"
        return f"Type_{addr}"

    def display_name(self):
        return self.name or self.default_name()

    def __repr__(self):
        return f"MethodTable({self.address:#x}, {self.display_name()!r})"


def read_method_table(bv, address, version):
    """Parse a MethodTable at `address`, raising ValueError if the bytes
    there don't look like a plausible MT (used both for real discovery and
    to reject false-positive candidates)."""

    header = bv.read(address, _HEADER_SIZE)
    if len(header) < _HEADER_SIZE:
        raise ValueError(f"could not read MT header at {address:#x}")

    mt = MethodTable(address, version)

    if version == NET70:
        (
            mt.component_size,
            mt.flags,
            mt.base_size,
            mt.related_type_address,
            vtable_count,
            iface_count,
            mt.hash_code,
        ) = struct.unpack("<HHIQHHI", header)
    else:
        (
            mt.flags,
            mt.base_size,
            mt.related_type_address,
            vtable_count,
            iface_count,
            mt.hash_code,
        ) = struct.unpack("<IIQHHI", header)

    if not (0 <= vtable_count < _MAX_SLOT_COUNT):
        raise ValueError(f"invalid vtable slot count {vtable_count} at {address:#x}")
    if not (0 <= iface_count < _MAX_SLOT_COUNT):
        raise ValueError(f"invalid interface count {iface_count} at {address:#x}")

    tail = bv.read(address + _HEADER_SIZE, 8 * (vtable_count + iface_count))
    if len(tail) < 8 * (vtable_count + iface_count):
        raise ValueError(f"truncated vtable/interface array at {address:#x}")

    longs = struct.unpack(f"<{vtable_count + iface_count}Q", tail)
    mt.vtable = list(longs[:vtable_count])
    mt.interface_addresses = list(longs[vtable_count:])

    if mt.element_type == ElementType.INTERFACE:
        if mt.base_size != 0:
            raise ValueError(f"interface MT with non-zero base size at {address:#x}")
        if mt.related_type_address != 0:
            raise ValueError(f"interface MT with non-zero related type at {address:#x}")
    elif mt.base_size < 0x10:
        raise ValueError(f"implausible base size {mt.base_size:#x} at {address:#x}")

    return mt


class MethodTableManager:
    def __init__(self, bv, version):
        self.bv = bv
        self.version = version
        self.by_address = {}
        self.object_mt = None
        self.string_mt = None

    def get(self, address):
        return self.by_address.get(address)

    def get_or_create(self, address):
        mt = self.by_address.get(address)
        if mt is not None:
            return mt
        mt = read_method_table(self.bv, address, self.version)
        self.by_address[address] = mt
        return mt

    def all_method_tables(self):
        return list(self.by_address.values())

    def is_likely_code_pointer(self, value):
        if value == 0:
            return True
        segment = self.bv.get_segment_at(value)
        return segment is not None and segment.executable

    def find_candidate_object_mts(self, pointer_scan):
        """System.Object has an extremely distinctive header: exactly 3
        vtable slots (ToString/Equals/GetHashCode), no interfaces, no base
        type, and a fixed 0x18 base size. We scan every candidate pointer
        location as if it were VTable[0] of such a header."""

        expected_flags = 0xA1000000 if self.version == NET70 else 0x50000000
        memory = self.bv
        seen = set()
        result = []

        for loc in pointer_scan.pointer_locations:
            raw = memory.read(loc, 32)
            if len(raw) < 32:
                continue
            v0, v1, v2, v3 = struct.unpack("<QQQQ", raw)

            if not (
                self.is_likely_code_pointer(v0)
                and self.is_likely_code_pointer(v1)
                and self.is_likely_code_pointer(v2)
                and not self.is_likely_code_pointer(v3)
            ):
                continue

            header = memory.read(loc - 0x18, 0x18)
            if len(header) < 0x18:
                continue

            flags_or_component, base_size, related_type, vtable_count, iface_count = (
                struct.unpack_from("<IIQHH", header)
            )
            # NOTE: for net70 the first dword straddles componentSize+flags;
            # for net80 it's the flags dword outright. Either way the whole
            # dword must equal the expected constant for Object.
            if vtable_count != 3 or iface_count != 0:
                continue
            if related_type != 0:
                continue
            if base_size != 0x18:
                continue
            if flags_or_component != expected_flags:
                continue

            addr = loc - 0x18
            if addr not in seen:
                seen.add(addr)
                result.append(addr)

        return result

    def find_string_mt_candidates(self):
        candidates = []
        for mt in self.all_method_tables():
            if (
                mt.related_type is self.object_mt
                and mt.element_type == ElementType.CLASS
                and mt.base_size == 0x16
            ):
                candidates.append(mt)
        return candidates


def crawl(bv, manager, pointer_scan, log=None):
    """End-to-end discovery: find System.Object, walk the induced
    inheritance graph to a fixed point, then identify System.String."""

    def _log(msg):
        if log:
            log(msg)

    if manager.object_mt is None:
        candidates = manager.find_candidate_object_mts(pointer_scan)
        if len(candidates) != 1:
            _log(
                f"expected exactly 1 System.Object candidate, found {len(candidates)}"
                + (": " + ", ".join(f"{a:#x}" for a in candidates) if candidates else "")
            )
            return manager

        mt = manager.get_or_create(candidates[0])
        mt.name = "System.Object"
        manager.object_mt = mt
        _log(f"assuming {mt.address:#x} is System.Object")

    _find_all_method_tables(manager, pointer_scan, log=_log)
    _log(f"found {len(manager.by_address)} method tables")

    if manager.string_mt is None:
        candidates = manager.find_string_mt_candidates()
        if len(candidates) == 1:
            manager.string_mt = candidates[0]
            manager.string_mt.name = "System.String"
            _log(f"assuming {manager.string_mt.address:#x} is System.String")
        elif candidates:
            _log(f"multiple System.String candidates found, skipping: {candidates}")
        else:
            _log("no System.String candidate found")

    return manager


def _find_all_method_tables(manager, pointer_scan, log=None):
    unmatched = list(pointer_scan.pointer_locations)

    for _pass in range(1, _MAX_PASSES):
        agenda = unmatched
        unmatched = []

        for current in agenda:
            raw = manager.bv.read(current, 8)
            if len(raw) < 8:
                continue
            (dereferenced,) = struct.unpack("<Q", raw)

            if not (pointer_scan.range_start <= dereferenced < pointer_scan.range_end):
                # Not a pointer into the metadata range -- could be a code
                # pointer (a vtable slot), never a base-type reference.
                continue

            related_type = manager.get(dereferenced)
            if related_type is None:
                unmatched.append(current)
                continue

            mt_address = current - _RELATED_TYPE_OFFSET
            try:
                mt = manager.get_or_create(mt_address)
            except ValueError:
                continue
            mt.related_type = related_type
            related_type.derived_types.add(mt)

            for iface_addr in mt.interface_addresses:
                if iface_addr == 0:
                    continue
                try:
                    iface_mt = manager.get_or_create(iface_addr)
                except ValueError:
                    continue
                mt.interfaces.append(iface_mt)

        if len(unmatched) >= len(agenda):
            break
