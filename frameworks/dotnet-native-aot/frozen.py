"""Frozen object annotation: compile-time-constant strings, SZ arrays, and
boxed value types that NativeAOT bakes straight into the image (the
FROZEN_OBJECT_REGION / 0xCE ReadyToRun section) instead of allocating on the
GC heap at startup.

Ported from washi1337/ghidra-nativeaot's
nativeaot/objectmodel/FrozenObjectAnnotator.java.
"""

import struct

from binaryninja import Symbol, SymbolType, Type

from .rtr import SECTION_FROZEN_OBJECT_REGION, FROZEN_SEGMENT_START_SYMBOL_NAME
from .codegen import instance_type_name

_STRING_LENGTH_OFFSET = 8
_ARRAY_LENGTH_OFFSET = 8
_MAX_STRING_LENGTH = 0x1_0000
_MAX_ARRAY_LENGTH = 0x1_0000


def annotate_frozen_objects(bv, manager, directory, pointer_scan, log=None):
    section = directory.section_by_type(SECTION_FROZEN_OBJECT_REGION)
    if section is None:
        if log:
            log("no frozen object section present in ReadyToRun directory")
        return 0

    if not bv.get_symbols_by_name(FROZEN_SEGMENT_START_SYMBOL_NAME):
        try:
            bv.define_user_symbol(
                Symbol(SymbolType.DataSymbol, section.start, FROZEN_SEGMENT_START_SYMBOL_NAME)
            )
        except Exception:
            pass

    locations = section.pointers_in_section(pointer_scan.pointer_locations)
    count = 0
    for location in locations:
        raw = bv.read(location, 8)
        if len(raw) < 8:
            continue
        (dereferenced,) = struct.unpack("<Q", raw)

        mt = manager.get(dereferenced)
        if mt is None:
            continue

        success = False
        if manager.string_mt is not None and mt.address == manager.string_mt.address:
            success = _annotate_string(bv, location, mt)
        elif mt.is_szarray:
            success = _annotate_szarray(bv, location, mt)
        elif mt.is_class or mt.is_value_type:
            success = _annotate_object(bv, location, mt)

        if success:
            count += 1

    if log:
        log(f"found {count} frozen objects")
    return count


def _annotate_string(bv, location, mt):
    try:
        instance_type = bv.get_type_by_name(instance_type_name(mt))

        raw = bv.read(location + _STRING_LENGTH_OFFSET, 4)
        if len(raw) < 4:
            return False
        (length,) = struct.unpack("<I", raw)
        if length >= _MAX_STRING_LENGTH:
            return False

        header_size = instance_type.width if instance_type else 12
        string_start = location + header_size
        string_end = string_start + length * 2

        terminator = bv.read(string_end, 1)
        if len(terminator) < 1 or terminator[0] != 0:
            return False

        if instance_type is not None:
            bv.define_user_data_var(location, instance_type)

        text = ""
        if length > 0:
            raw_chars = bv.read(string_start, length * 2)
            text = raw_chars.decode("utf-16-le", errors="replace")
            bv.define_user_data_var(string_start, Type.array(Type.wide_char(2), length + 1))

        label = _sanitize_for_label(text) if length > 0 else "String_Empty"
        bv.define_user_symbol(
            Symbol(SymbolType.DataSymbol, location, f"dn_{label}_{location:#x}")
        )
        if text:
            bv.set_comment_at(location, text)

        return True
    except Exception:
        return False


def _annotate_szarray(bv, location, mt):
    try:
        instance_type = bv.get_type_by_name(instance_type_name(mt))
        if instance_type is None:
            return False

        raw = bv.read(location + _ARRAY_LENGTH_OFFSET, 4)
        if len(raw) < 4:
            return False
        (length,) = struct.unpack("<I", raw)
        if length >= _MAX_ARRAY_LENGTH:
            return False

        bv.define_user_data_var(location, instance_type)

        if length > 0:
            data_start = location + instance_type.width
            element_member = instance_type.structure["Data"]
            element_type = element_member.type.element_type
            bv.define_user_data_var(data_start, Type.array(element_type, length))

        bv.define_user_symbol(
            Symbol(SymbolType.DataSymbol, location, f"{mt.display_name()}_{location:#x}")
        )
        return True
    except Exception:
        return False


def _annotate_object(bv, location, mt):
    try:
        instance_type = bv.get_type_by_name(instance_type_name(mt))
        if instance_type is None:
            return False
        bv.define_user_data_var(location, instance_type)
        bv.define_user_symbol(
            Symbol(SymbolType.DataSymbol, location, f"{mt.display_name()}_{location:#x}")
        )
        return True
    except Exception:
        return False


def _sanitize_for_label(text, max_len=56):
    text = text[:max_len]
    out = [ch if (ch.isalnum() or ch == "_") else "_" for ch in text]
    return "".join(out) or "empty"
