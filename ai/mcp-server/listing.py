"""The consolidated `list` tool: one primitive covering every listing
-shaped read tool -- functions, symbols, types, sections, imports,
exports, strings -- that reading.py used to expose as seven separate
tools with seven separate ad hoc pagination signatures (several with no
pagination at all, e.g. `get_types()`/`get_sections()`/`get_imports()`/
`get_exports()`). See ADR-0038's "Tool surface" section for why these
specifically collapse into one shared filter/fields/limit/offset shape
and the action-shaped tools (rename_function, patch_asm, ...) don't.

Always registered, no gating setting -- same tier as reading.py's tools.
"""

from typing import List, Literal, Optional

from binaryninja import SectionSemantics, SymbolBinding, SymbolType
from binaryninja.enums import StringType
from mcp.types import CallToolResult

from .binary_context import get_current_view
from .concurrency import log_tool_call, serialized
from .rendering import filter_rows, paginate, project, render_table, tool_result

_IMPORT_SYMBOL_TYPES = {
    SymbolType.ImportAddressSymbol,
    SymbolType.ImportedFunctionSymbol,
    SymbolType.ImportedDataSymbol,
    SymbolType.ExternalSymbol,
}

Kind = Literal["functions", "symbols", "types", "sections", "imports", "exports", "strings"]


def _enum_name(enum_cls, raw_value) -> str:
    """BN's live symbol/string/section objects expose type/semantics as
    plain ints, not enum instances -- wrap in the enum class and take
    .name for the readable form."""
    return enum_cls(raw_value).name


def _functions_rows(bv) -> list:
    return [{"name": f.name, "addr": hex(f.start)} for f in bv.functions]


def _symbols_rows(bv) -> list:
    return [{"name": s.name, "addr": hex(s.address), "type": _enum_name(SymbolType, s.type)} for s in bv.get_symbols()]


def _types_rows(bv) -> list:
    # bv.types keys are QualifiedName objects, not plain str -- stringify
    # explicitly, or this ends up embedded as-is in structuredContent,
    # which isn't JSON-serializable and crashes the response mid-stream
    # (server sends 200 + chunked headers, then the body generator dies).
    return [{"name": str(name), "definition": str(t)} for name, t in bv.types.items()]


def _sections_rows(bv) -> list:
    rows = []
    for s in bv.sections.values():
        seg = bv.get_segment_at(s.start)
        rows.append(
            {
                "name": s.name,
                "start": hex(s.start),
                "end": hex(s.end),
                "semantics": _enum_name(SectionSemantics, s.semantics),
                "r": bool(seg.readable) if seg else None,
                "w": bool(seg.writable) if seg else None,
                "x": bool(seg.executable) if seg else None,
            }
        )
    return rows


def _imports_rows(bv) -> list:
    return [
        {"name": s.name, "addr": hex(s.address), "type": _enum_name(SymbolType, s.type)}
        for s in bv.get_symbols()
        if s.type in _IMPORT_SYMBOL_TYPES
    ]


def _exports_rows(bv) -> list:
    return [
        {"name": s.name, "addr": hex(s.address), "type": _enum_name(SymbolType, s.type)}
        for s in bv.get_symbols()
        if s.type not in _IMPORT_SYMBOL_TYPES and s.binding == SymbolBinding.GlobalBinding
    ]


def _strings_rows(bv) -> list:
    return [
        {"addr": hex(s.start), "length": s.length, "type": _enum_name(StringType, s.type), "value": s.value}
        for s in bv.get_strings()
    ]


# kind -> (row producer, field to match `name_regex` against)
_KIND_PRODUCERS = {
    "functions": (_functions_rows, "name"),
    "symbols": (_symbols_rows, "name"),
    "types": (_types_rows, "name"),
    "sections": (_sections_rows, "name"),
    "imports": (_imports_rows, "name"),
    "exports": (_exports_rows, "name"),
    "strings": (_strings_rows, "value"),
}


@serialized
def list_records(
    kind: Kind,
    name_regex: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 100,
    offset: int = 0,
) -> CallToolResult:
    """List records from the current binary.

    kind: "functions", "symbols", "types", "sections", "imports",
    "exports", or "strings".
    name_regex: optional filter against each record's name (or value, for
    strings) -- substring match (case-insensitive), or a regex if it
    compiles as one. Applied before pagination, so limit/offset page
    through the *filtered* set, not the full unfiltered one.
    fields: optional list of field names to keep, narrowing and reordering
    columns; omit for every field. Available fields depend on kind: both
    "name"/"addr" for functions; "name"/"addr"/"type" for symbols/imports/
    exports; "name"/"definition" for types; "name"/"start"/"end"/
    "semantics"/"r"/"w"/"x" for sections; "addr"/"length"/"type"/"value"
    for strings.
    limit/offset: pagination over the filtered set (default limit 100).
    """
    producer, filter_key = _KIND_PRODUCERS[kind]
    bv = get_current_view()
    rows = filter_rows(producer(bv), name_regex, filter_key)
    total = len(rows)
    page = project(paginate(rows, limit, offset), fields)
    return tool_result(
        render_table(page, fields),
        {"kind": kind, "rows": page, "total": total, "limit": limit, "offset": offset},
    )


def register(mcp) -> None:
    mcp.add_tool(log_tool_call(list_records), name="list", description=list_records.__doc__)
