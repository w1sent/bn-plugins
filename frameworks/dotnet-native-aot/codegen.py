"""Materializes a populated MethodTableManager into Binary Ninja: struct
types for every MethodTable/instance layout, data vars + symbols at every MT
address, and named+retyped functions at every reachable vtable slot.

This is the Python/BN counterpart of MethodTable.commitToDB,
MethodTableCrawler.createMTStructures/assignMethods, and
assignSystemObjectNames/assignSystemStringNames/assignSzArrayNames in
washi1337/ghidra-nativeaot.

Simplification vs. the Ghidra/IDA tools: base-type and interface pointers,
and vtable/interface array entries, are typed `void*` rather than as fully
cross-referenced named struct pointers. Building a truly typed graph would
need either two-pass forward type references or topological ordering across
a graph that can contain cycles (generic recursion); `void*` sidesteps that
at the cost of one dereference of manual clicking in BN's type viewer. Field
offsets, sizes, names, and the recovered function graph are unaffected.
"""

from binaryninja import Symbol, SymbolType, Type, StructureBuilder

from .objectmodel import ElementType, OBJECT_METHOD_NAMES


def _void_ptr(bv):
    return Type.pointer(bv.arch, Type.void())


def mt_type_name_of(mt):
    return f"{mt.display_name()}_MT"


def instance_type_name(mt):
    return mt.display_name()


def build_mt_struct_type(bv, mt):
    """`<Name>_MT` -- the raw MethodTable header + vtable + interface array."""

    builder = StructureBuilder.create()
    if mt.version == "net70":
        builder.append(Type.int(2, False), "usComponentSize")
        builder.append(Type.int(2, False), "usFlags")
    else:
        builder.append(Type.int(4, False), "uFlags")
    builder.append(Type.int(4, False), "uBaseSize")
    builder.append(_void_ptr(bv), "relatedType")
    builder.append(Type.int(2, False), "usNumVtableSlots")
    builder.append(Type.int(2, False), "usNumInterfaces")
    builder.append(Type.int(4, False), "uHashCode")

    for i in range(len(mt.vtable)):
        builder.append(_void_ptr(bv), f"vtbl_{i}")
    if mt.interface_addresses:
        builder.append(
            Type.array(_void_ptr(bv), len(mt.interface_addresses)), "Interfaces"
        )

    return builder.immutable_copy()


def build_instance_struct_type(bv, mt, mt_ptr_type):
    """`<Name>` -- the object layout: mt pointer + data padding out to
    base_size (object sync-block header lives 8 bytes *before* this, so
    isn't part of the struct)."""

    builder = StructureBuilder.create()
    builder.append(Type.pointer(bv.arch, mt_ptr_type), "mt")
    padding = max(0, mt.data_size)
    if padding:
        builder.append(Type.array(Type.int(1, False), padding), "data")
    return builder.immutable_copy()


def commit_method_table(bv, mt):
    """Define/refresh the MT struct type, instance struct type, and the
    data var + label at the MT's address. Returns True on success."""

    try:
        mt_type = build_mt_struct_type(bv, mt)
        mt_type_name = mt_type_name_of(mt)
        bv.define_user_type(mt_type_name, mt_type)
        named_mt_type = bv.get_type_by_name(mt_type_name) or mt_type

        instance_type = build_instance_struct_type(bv, mt, named_mt_type)
        bv.define_user_type(instance_type_name(mt), instance_type)

        bv.define_user_data_var(mt.address, named_mt_type)
        bv.define_user_symbol(
            Symbol(SymbolType.DataSymbol, mt.address, f"{mt.display_name()}_MT")
        )
        return True
    except Exception:
        return False


def apply_special_layouts(bv, manager):
    """System.String and SZ-array instances have a fixed, well-known shape
    (see Runtime.Base/src/System/String.cs and Array.cs upstream) that
    differs from the generic mt+padding layout -- override it here."""

    if manager.string_mt is not None:
        mt = manager.string_mt
        mt_type = bv.get_type_by_name(mt_type_name_of(mt))
        builder = StructureBuilder.create()
        builder.append(Type.pointer(bv.arch, mt_type) if mt_type else _void_ptr(bv), "mt")
        builder.append(Type.int(4, False), "_length")
        builder.append(Type.array(Type.wide_char(2), 0), "_firstChar")
        bv.define_user_type(instance_type_name(mt), builder.immutable_copy())

    _ELEMENT_BN_TYPES = {
        ElementType.BOOLEAN: lambda bv: Type.bool(),
        ElementType.CHAR: lambda bv: Type.wide_char(2),
        ElementType.SBYTE: lambda bv: Type.int(1, True),
        ElementType.BYTE: lambda bv: Type.int(1, False),
        ElementType.INT16: lambda bv: Type.int(2, True),
        ElementType.UINT16: lambda bv: Type.int(2, False),
        ElementType.INT32: lambda bv: Type.int(4, True),
        ElementType.UINT32: lambda bv: Type.int(4, False),
        ElementType.INT64: lambda bv: Type.int(8, True),
        ElementType.UINT64: lambda bv: Type.int(8, False),
        ElementType.INTPTR: lambda bv: _void_ptr(bv),
        ElementType.UINTPTR: lambda bv: _void_ptr(bv),
        ElementType.SINGLE: lambda bv: Type.float(4),
        ElementType.DOUBLE: lambda bv: Type.float(8),
    }

    for mt in manager.all_method_tables():
        if not mt.is_szarray:
            continue
        try:
            mt_type = bv.get_type_by_name(mt_type_name_of(mt))
            builder = StructureBuilder.create()
            builder.append(Type.pointer(bv.arch, mt_type) if mt_type else _void_ptr(bv), "mt")
            builder.append(Type.int(4, False), "Length")
            builder.append(Type.int(4, False), "Padding")
            factory = _ELEMENT_BN_TYPES.get(mt.related_type.element_type if mt.related_type else -1)
            element_type = factory(bv) if factory else _void_ptr(bv)
            builder.append(Type.array(element_type, 0), "Data")
            bv.define_user_type(instance_type_name(mt), builder.immutable_copy())
        except Exception:
            continue


def _is_auto_name(name):
    return any(
        name.startswith(p) for p in ("sub_", "loc_", "unk_", "j_sub_", "FUN_", "data_")
    )


def assign_methods(bv, manager, tag_cb=None):
    """BFS out from System.Object over the induced inheritance graph,
    naming/retyping the function at every executable vtable slot the first
    time it's encountered (inherited slots are visited via the base type
    first, so overrides never clobber the introducing type's name)."""

    if manager.object_mt is None:
        return {"functions_named": 0}

    visited = set()
    agenda = [manager.object_mt]
    named = 0

    while agenda:
        mt = agenda.pop(0)
        if mt.address in visited:
            continue
        visited.add(mt.address)
        agenda.extend(mt.derived_types)

        for i, entry_point in enumerate(mt.vtable):
            segment = bv.get_segment_at(entry_point)
            if segment is None or not segment.executable:
                continue

            func = bv.get_function_at(entry_point)
            if func is None:
                func = bv.create_user_function(entry_point)
            if func is None:
                continue

            if _is_auto_name(func.name):
                default_name = (
                    OBJECT_METHOD_NAMES[i] if i < len(OBJECT_METHOD_NAMES) else f"Method_{i}"
                )
                new_name = f"{mt.display_name()}::{default_name}"
                try:
                    bv.define_user_symbol(
                        Symbol(SymbolType.FunctionSymbol, entry_point, new_name)
                    )
                    named += 1
                    if tag_cb:
                        tag_cb(entry_point, f"{mt.display_name()} vtable slot {i}")
                except Exception:
                    pass

            _retype_this_param(bv, func, mt)

    return {"functions_named": named}


def _retype_this_param(bv, func, mt):
    try:
        instance_type = bv.get_type_by_name(instance_type_name(mt))
        if instance_type is None:
            return
        this_ptr = Type.pointer(bv.arch, instance_type)
        current = func.function_type
        params = list(current.parameters)
        if not params:
            return
        params[0].name = "this"
        params[0].type = this_ptr
        func.function_type = Type.function(
            current.return_value, params, calling_convention=current.calling_convention
        )
    except Exception:
        pass


def commit_all(bv, manager, log=None):
    ok = 0
    for mt in manager.all_method_tables():
        if commit_method_table(bv, mt):
            ok += 1
    if log:
        log(f"committed {ok}/{len(manager.by_address)} method table types")
    apply_special_layouts(bv, manager)
    return ok
