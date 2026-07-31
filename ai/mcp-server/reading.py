"""Read-only RE-assistant tools: single-target lookups (get_function,
get_xrefs_to/from, get_type, get_data) and the cross-cutting `search`.
Listing-shaped tools (functions/symbols/types/sections/imports/exports/
strings) moved to listing.py's consolidated `list` tool -- see ADR-0038.

Unlike scripting/write/etc., these have no gating setting -- they're the
core, always-available read-only use case (see TODO.md phase 3). All of
them operate on `binary_context.get_current_view()`, i.e. whichever binary
is focused in the GUI right now (or explicitly selected -- see
administration.py).
"""

import re
from typing import List, Optional, Union

from binaryninja import SymbolType
from mcp.types import CallToolResult

from .binary_context import get_current_view
from .concurrency import log_tool_call, serialized
from .listing import list_records
from .rendering import render_kv, render_table, tool_result

_IL_LEVELS = ("disassembly", "llil", "mlil", "hlil", "llil_ssa", "mlil_ssa", "hlil_ssa")


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
    """BN's live symbol/string/section objects expose type/semantics as
    plain ints, not enum instances -- wrap in the enum class and take
    .name for the readable form."""
    return enum_cls(raw_value).name


@serialized
def get_function(name_or_addr: Union[int, str], il_level: str = "disassembly") -> CallToolResult:
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

    meta = {
        "name": f.name,
        "start": hex(f.start),
        "symbol_type": _enum_name(SymbolType, f.symbol.type),
        "il_level": il_level,
    }
    text = render_kv(meta) + "\n\n" + render_table(lines, fields=["address", "text"])
    return tool_result(text, {**meta, "lines": lines})


@serialized
def get_xrefs_to(addr: Union[int, str], limit: int = 100, offset: int = 0) -> CallToolResult:
    """Get cross-references (code and data) to an address, paginated
    independently for each (limit/offset apply to both lists)."""
    bv = get_current_view()
    a = _parse_addr(addr)
    code_rows = [{"function": r.function.name, "address": hex(r.address)} for r in bv.get_code_refs(a)]
    data_rows = [{"address": hex(x)} for x in bv.get_data_refs(a)]
    code_total, data_total = len(code_rows), len(data_rows)
    code_page = code_rows[offset : offset + limit]
    data_page = data_rows[offset : offset + limit]
    text = (
        f"code_refs (total {code_total}):\n"
        + render_table(code_page)
        + f"\n\ndata_refs (total {data_total}):\n"
        + render_table(data_page)
    )
    return tool_result(
        text,
        {"code_refs": code_page, "code_total": code_total, "data_refs": data_page, "data_total": data_total},
    )


@serialized
def get_xrefs_from(addr: Union[int, str], limit: int = 100, offset: int = 0) -> CallToolResult:
    """Get cross-references (code and data) from an address, paginated
    independently for each (limit/offset apply to both lists)."""
    bv = get_current_view()
    a = _parse_addr(addr)
    code_rows = [{"address": hex(x)} for x in bv.get_code_refs_from(a)]
    data_rows = [{"address": hex(x)} for x in bv.get_data_refs_from(a)]
    code_total, data_total = len(code_rows), len(data_rows)
    code_page = code_rows[offset : offset + limit]
    data_page = data_rows[offset : offset + limit]
    text = (
        f"code_refs (total {code_total}):\n"
        + render_table(code_page)
        + f"\n\ndata_refs (total {data_total}):\n"
        + render_table(data_page)
    )
    return tool_result(
        text,
        {"code_refs": code_page, "code_total": code_total, "data_refs": data_page, "data_total": data_total},
    )


@serialized
def get_type(name: str) -> CallToolResult:
    """Get a specific type's definition by name."""
    bv = get_current_view()
    t = bv.get_type_by_name(name)
    if t is None:
        raise ValueError(f"no type named {name!r}")
    meta = {"name": name, "definition": str(t)}
    return tool_result(render_kv(meta), meta)


@serialized
def get_data(addr: Union[int, str], size: int) -> CallToolResult:
    """Read raw bytes at an address, returned as a hex string."""
    bv = get_current_view()
    a = _parse_addr(addr)
    data = bv.read(a, size)
    meta = {"address": hex(a), "size": len(data), "hex": data.hex()}
    return tool_result(render_kv(meta), meta)


def _matches(pattern: str, regex: Optional[re.Pattern], text: str) -> bool:
    if not text:
        return False
    if regex:
        return bool(regex.search(text))
    return pattern.lower() in text.lower()


@serialized
def search(pattern: str, limit: int = 50) -> CallToolResult:
    """Search function names, symbol names, and defined strings in the
    current binary for `pattern` (substring, or a regex if `pattern`
    compiles as one). For filtering *one* specific kind instead of all
    three at once, prefer `list(kind, name_regex=pattern)`."""
    bv = get_current_view()
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        regex = None

    results: List[dict] = []

    def add(kind: str, name: str, address: int) -> bool:
        results.append({"kind": kind, "name": name, "address": hex(address)})
        return len(results) >= limit

    for f in bv.functions:
        if _matches(pattern, regex, f.name) and add("function", f.name, f.start):
            return tool_result(render_table(results), {"results": results})

    for s in bv.get_symbols():
        if _matches(pattern, regex, s.name) and add("symbol", s.name, s.address):
            return tool_result(render_table(results), {"results": results})

    for s in bv.get_strings():
        if _matches(pattern, regex, s.value) and add("string", s.value, s.start):
            return tool_result(render_table(results), {"results": results})

    return tool_result(render_table(results), {"results": results})


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
    (get_xrefs_to, "get_xrefs_to"),
    (get_xrefs_from, "get_xrefs_from"),
    (get_type, "get_type"),
    (get_data, "get_data"),
    (search, "search"),
)

# Resource dumps used to hardcode limit=1_000_000 -- go through the same
# consolidated, paginated `list` primitive instead, with a bound generous
# enough to cover ordinary binaries without reintroducing an unbounded dump.
_RESOURCE_LIMIT = 2000


def register(mcp) -> None:
    for fn, name in _TOOLS:
        mcp.add_tool(log_tool_call(fn), name=name, description=fn.__doc__)

    mcp.resource(
        "binary://metadata", name="binary_metadata", description="Current binary's name, arch, platform, entry point, size"
    )(_binary_metadata)
    mcp.resource(
        "binary://functions", name="binary_functions", description="Function list of the current binary (bounded)"
    )(lambda: list_records(kind="functions", limit=_RESOURCE_LIMIT, offset=0))
    mcp.resource(
        "binary://symbols", name="binary_symbols", description="Symbol table of the current binary (bounded)"
    )(lambda: list_records(kind="symbols", limit=_RESOURCE_LIMIT, offset=0))
    mcp.resource("binary://types", name="binary_types", description="Type definitions in the current binary (bounded)")(
        lambda: list_records(kind="types", limit=_RESOURCE_LIMIT, offset=0)
    )
    mcp.resource("binary://sections", name="binary_sections", description="Section list of the current binary")(
        lambda: list_records(kind="sections", limit=_RESOURCE_LIMIT, offset=0)
    )
