"""Read-only RE-assistant tools + resources: functions, symbols, xrefs,
types, data, strings, sections, imports/exports, search.

Unlike scripting/write/etc., read tools have no gating setting -- they're
the core, always-available read-only use case (see TODO.md phase 3). All of
them operate on `binary_context.get_current_view()`, i.e. whichever binary
is focused in the GUI right now.
"""

import re
from typing import Optional, Union

from binaryninja import SectionSemantics, SymbolBinding, SymbolType
from binaryninja.enums import StringType

from .binary_context import get_current_view
from .concurrency import log_tool_call, serialized

_IL_LEVELS = ("disassembly", "llil", "mlil", "hlil", "llil_ssa", "mlil_ssa", "hlil_ssa")

_IMPORT_SYMBOL_TYPES = {
    SymbolType.ImportAddressSymbol,
    SymbolType.ImportedFunctionSymbol,
    SymbolType.ImportedDataSymbol,
    SymbolType.ExternalSymbol,
}


def _parse_addr(value: Union[int, str]) -> int:
    if isinstance(value, int):
        return value
    return int(value, 0)


def _resolve_function(bv, name_or_addr: Union[int, str]):
    if not isinstance(name_or_addr, int):
        try:
            addr = int(name_or_addr, 0)
        except ValueError:
            addr = None
        if addr is None:
            matches = [f for f in bv.functions if f.name == name_or_addr]
            if not matches:
                raise ValueError(f"no function named {name_or_addr!r}")
            return matches[0]
        name_or_addr = addr
    f = bv.get_function_at(name_or_addr)
    if f is None:
        raise ValueError(f"no function at {hex(name_or_addr)}")
    return f


def _disassembly_lines(f) -> list:
    return [{"address": hex(addr), "text": "".join(t.text for t in tokens)} for tokens, addr in f.instructions]


def _il_lines(il) -> list:
    return [{"address": hex(line.address), "text": str(line)} for line in il.instructions]


def _enum_name(enum_cls, raw_value) -> str:
    """BN's live symbol/string/section objects expose type/semantics as plain
    ints, not enum instances -- str() on them just prints the int back, so
    wrap in the enum class and take .name for the readable form."""
    return enum_cls(raw_value).name


@serialized
def get_function(name_or_addr: Union[int, str], il_level: str = "disassembly") -> dict:
    """Get a function's metadata plus its disassembly or IL.

    name_or_addr: function name, or address as an int or hex/decimal string.
    il_level: one of "disassembly", "llil", "mlil", "hlil", "llil_ssa",
    "mlil_ssa", "hlil_ssa" (default "disassembly")."""
    if il_level not in _IL_LEVELS:
        raise ValueError(f"il_level must be one of {_IL_LEVELS}")
    bv = get_current_view()
    f = _resolve_function(bv, name_or_addr)
    if il_level == "disassembly":
        lines = _disassembly_lines(f)
    else:
        il = getattr(f, il_level)
        if il is None:
            raise ValueError(f"{il_level} is not available for this function")
        lines = _il_lines(il)
    return {
        "name": f.name,
        "start": hex(f.start),
        "symbol_type": _enum_name(SymbolType, f.symbol.type),
        "il_level": il_level,
        "lines": lines,
    }


@serialized
def get_functions(limit: int = 100, offset: int = 0) -> dict:
    """List functions in the current binary, paginated."""
    bv = get_current_view()
    funcs = list(bv.functions)
    page = funcs[offset : offset + limit]
    return {"functions": [{"name": f.name, "start": hex(f.start)} for f in page], "total": len(funcs)}


@serialized
def get_symbols(limit: int = 200, offset: int = 0) -> dict:
    """List symbols (names, addresses, types) in the current binary, paginated."""
    bv = get_current_view()
    syms = bv.get_symbols()
    page = syms[offset : offset + limit]
    return {
        "symbols": [
            {"name": s.name, "address": hex(s.address), "type": _enum_name(SymbolType, s.type)} for s in page
        ],
        "total": len(syms),
    }


@serialized
def get_xrefs_to(addr: Union[int, str]) -> dict:
    """Get cross-references (code and data) to an address."""
    bv = get_current_view()
    a = _parse_addr(addr)
    code_refs = [{"function": r.function.name, "address": hex(r.address)} for r in bv.get_code_refs(a)]
    data_refs = [hex(x) for x in bv.get_data_refs(a)]
    return {"code_refs": code_refs, "data_refs": data_refs}


@serialized
def get_xrefs_from(addr: Union[int, str]) -> dict:
    """Get cross-references (code and data) from an address."""
    bv = get_current_view()
    a = _parse_addr(addr)
    code_refs = [hex(x) for x in bv.get_code_refs_from(a)]
    data_refs = [hex(x) for x in bv.get_data_refs_from(a)]
    return {"code_refs": code_refs, "data_refs": data_refs}


@serialized
def get_types() -> dict:
    """List all user-defined types in the current binary."""
    bv = get_current_view()
    return {"types": [{"name": name, "definition": str(t)} for name, t in bv.types.items()]}


@serialized
def get_type(name: str) -> dict:
    """Get a specific type's definition by name."""
    bv = get_current_view()
    t = bv.get_type_by_name(name)
    if t is None:
        raise ValueError(f"no type named {name!r}")
    return {"name": name, "definition": str(t)}


@serialized
def get_data(addr: Union[int, str], size: int) -> dict:
    """Read raw bytes at an address, returned as a hex string."""
    bv = get_current_view()
    a = _parse_addr(addr)
    data = bv.read(a, size)
    return {"address": hex(a), "size": len(data), "hex": data.hex()}


@serialized
def get_strings(limit: int = 200, offset: int = 0) -> dict:
    """List strings found in the current binary, paginated."""
    bv = get_current_view()
    strings = bv.get_strings()
    page = strings[offset : offset + limit]
    return {
        "strings": [
            {"address": hex(s.start), "length": s.length, "type": _enum_name(StringType, s.type), "value": s.value}
            for s in page
        ],
        "total": len(strings),
    }


@serialized
def get_sections() -> dict:
    """List the current binary's sections, with permissions inferred from
    the segment each section lives in."""
    bv = get_current_view()
    result = []
    for s in bv.sections.values():
        seg = bv.get_segment_at(s.start)
        result.append(
            {
                "name": s.name,
                "start": hex(s.start),
                "end": hex(s.end),
                "semantics": _enum_name(SectionSemantics, s.semantics),
                "readable": bool(seg.readable) if seg else None,
                "writable": bool(seg.writable) if seg else None,
                "executable": bool(seg.executable) if seg else None,
            }
        )
    return {"sections": result}


@serialized
def get_imports() -> dict:
    """List imported functions/data in the current binary."""
    bv = get_current_view()
    syms = [s for s in bv.get_symbols() if s.type in _IMPORT_SYMBOL_TYPES]
    return {
        "imports": [{"name": s.name, "address": hex(s.address), "type": _enum_name(SymbolType, s.type)} for s in syms]
    }


@serialized
def get_exports() -> dict:
    """List exported (globally visible) functions/data in the current binary."""
    bv = get_current_view()
    syms = [
        s
        for s in bv.get_symbols()
        if s.type not in _IMPORT_SYMBOL_TYPES and s.binding == SymbolBinding.GlobalBinding
    ]
    return {
        "exports": [{"name": s.name, "address": hex(s.address), "type": _enum_name(SymbolType, s.type)} for s in syms]
    }


def _matches(pattern: str, regex: Optional[re.Pattern], text: str) -> bool:
    if not text:
        return False
    if regex:
        return bool(regex.search(text))
    return pattern.lower() in text.lower()


@serialized
def search(pattern: str, limit: int = 50) -> dict:
    """Search function names, symbol names, and defined strings in the
    current binary for `pattern` (substring, or a regex if `pattern`
    compiles as one)."""
    bv = get_current_view()
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        regex = None

    results = []

    for f in bv.functions:
        if _matches(pattern, regex, f.name):
            results.append({"kind": "function", "name": f.name, "address": hex(f.start)})
            if len(results) >= limit:
                return {"results": results}

    for s in bv.get_symbols():
        if _matches(pattern, regex, s.name):
            results.append({"kind": "symbol", "name": s.name, "address": hex(s.address)})
            if len(results) >= limit:
                return {"results": results}

    for s in bv.get_strings():
        if _matches(pattern, regex, s.value):
            results.append({"kind": "string", "value": s.value, "address": hex(s.start)})
            if len(results) >= limit:
                return {"results": results}

    return {"results": results}


def _binary_metadata() -> dict:
    bv = get_current_view()
    return {
        "filename": bv.file.filename,
        "view_type": bv.view_type,
        "arch": bv.arch.name if bv.arch else None,
        "platform": bv.platform.name if bv.platform else None,
        "entry_point": hex(bv.entry_point),
        "start": hex(bv.start),
        "end": hex(bv.end),
    }


_TOOLS = (
    (get_function, "get_function"),
    (get_functions, "get_functions"),
    (get_symbols, "get_symbols"),
    (get_xrefs_to, "get_xrefs_to"),
    (get_xrefs_from, "get_xrefs_from"),
    (get_types, "get_types"),
    (get_type, "get_type"),
    (get_data, "get_data"),
    (get_strings, "get_strings"),
    (get_sections, "get_sections"),
    (get_imports, "get_imports"),
    (get_exports, "get_exports"),
    (search, "search"),
)


def register(mcp) -> None:
    for fn, name in _TOOLS:
        mcp.add_tool(log_tool_call(fn), name=name, description=fn.__doc__)

    mcp.resource(
        "binary://metadata", name="binary_metadata", description="Current binary's name, arch, platform, entry point, size"
    )(_binary_metadata)
    mcp.resource(
        "binary://functions", name="binary_functions", description="Full function list of the current binary"
    )(lambda: get_functions(limit=1_000_000, offset=0))
    mcp.resource(
        "binary://symbols", name="binary_symbols", description="Full symbol table of the current binary"
    )(lambda: get_symbols(limit=1_000_000, offset=0))
    mcp.resource("binary://types", name="binary_types", description="All type definitions in the current binary")(
        get_types
    )
    mcp.resource("binary://sections", name="binary_sections", description="Section list of the current binary")(
        get_sections
    )
