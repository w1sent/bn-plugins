"""Safe write tools: rename, comment, type, struct, function creation.

Gated by `mcp_server.write_enabled` (default on) -- these are the low-risk,
easily reversible tier (see TODO.md phase 4): they only ever add/replace
user-attributed metadata (names, comments, types, function boundaries), never
touch the binary's actual bytes. That's the `destructive_write_enabled` tier
instead (patch_asm/patch_c/edit_hex, a later phase).

All of them operate on `binary_context.get_current_view()`, same as the read
tools -- no explicit binary selection yet (that's `select_binary`, added in
the administration phase).
"""

from pathlib import Path
from typing import Union

import binaryninja
from binaryninja import Symbol
from mcp.types import CallToolResult

from .binary_context import get_current_view
from .concurrency import log_tool_call, serialized
from .reading import _parse_addr, _resolve_function
from .rendering import render_kv, tool_result


@serialized
def rename_function(addr: Union[int, str], name: str) -> CallToolResult:
    """Rename a function, identified by its address."""
    bv = get_current_view()
    f = _resolve_function(bv, addr)
    old_name = f.name
    f.name = name
    binaryninja.log_info(f"[mcp-server] rename_function: {old_name!r} -> {name!r} @ {hex(f.start)}")
    meta = {"address": hex(f.start), "old_name": old_name, "new_name": name}
    return tool_result(render_kv(meta), meta)


@serialized
def rename_symbol(addr: Union[int, str], name: str) -> CallToolResult:
    """Rename the symbol at an address (function or data)."""
    bv = get_current_view()
    a = _parse_addr(addr)
    sym = bv.get_symbol_at(a)
    if sym is None:
        raise ValueError(f"no symbol at {hex(a)}")
    old_name = sym.name
    bv.define_user_symbol(Symbol(sym.type, sym.address, name))
    binaryninja.log_info(f"[mcp-server] rename_symbol: {old_name!r} -> {name!r} @ {hex(a)}")
    meta = {"address": hex(a), "old_name": old_name, "new_name": name}
    return tool_result(render_kv(meta), meta)


@serialized
def set_comment(addr: Union[int, str], comment: str) -> CallToolResult:
    """Set a comment at an address."""
    bv = get_current_view()
    a = _parse_addr(addr)
    bv.set_comment_at(a, comment)
    meta = {"address": hex(a), "comment": comment}
    return tool_result(render_kv(meta), meta)


@serialized
def set_function_comment(addr: Union[int, str], comment: str) -> CallToolResult:
    """Set a function-level comment, identified by the function's address."""
    bv = get_current_view()
    f = _resolve_function(bv, addr)
    f.comment = comment
    meta = {"address": hex(f.start), "comment": comment}
    return tool_result(render_kv(meta), meta)


@serialized
def create_struct(c_struct: str) -> CallToolResult:
    """Define a struct type in the current binary from C struct syntax, e.g.
    "struct node { int32_t id; struct node* next; };"."""
    bv = get_current_view()
    t, name = bv.parse_type_string(c_struct)
    bv.define_user_type(name, t)
    meta = {"name": str(name), "definition": str(t)}
    return tool_result(render_kv(meta), meta)


@serialized
def load_header(path: str) -> CallToolResult:
    """Parse a C header file and define all the types it declares in the
    current binary."""
    bv = get_current_view()
    header_path = Path(path).expanduser()
    source = header_path.read_text()
    result = bv.parse_types_from_string(source, include_dirs=[str(header_path.parent)])
    bv.define_user_types(list(result.types.items()), None)
    defined = [str(name) for name in result.types.keys()]
    meta = {"defined_types": defined}
    return tool_result(render_kv({"defined_types": ", ".join(defined)}), meta)


@serialized
def set_type(addr: Union[int, str], type_name: str) -> CallToolResult:
    """Apply a data type to an address, e.g. type_name="int32_t" or a
    previously-defined struct name. Defines (or replaces) a data variable at
    that address with the given type."""
    bv = get_current_view()
    a = _parse_addr(addr)
    dv = bv.define_user_data_var(a, type_name)
    if dv is None:
        raise ValueError(f"could not define a data variable of type {type_name!r} at {hex(a)}")
    meta = {"address": hex(a), "type": str(dv.type)}
    return tool_result(render_kv(meta), meta)


@serialized
def create_function(addr: Union[int, str]) -> CallToolResult:
    """Create a function at an address."""
    bv = get_current_view()
    a = _parse_addr(addr)
    f = bv.create_user_function(a)
    if f is None:
        raise ValueError(f"could not create a function at {hex(a)}")
    meta = {"address": hex(f.start), "name": f.name}
    return tool_result(render_kv(meta), meta)


_TOOLS = (
    (rename_function, "rename_function"),
    (rename_symbol, "rename_symbol"),
    (set_comment, "set_comment"),
    (set_function_comment, "set_function_comment"),
    (create_struct, "create_struct"),
    (load_header, "load_header"),
    (set_type, "set_type"),
    (create_function, "create_function"),
)


def register(mcp) -> None:
    for fn, name in _TOOLS:
        mcp.add_tool(log_tool_call(fn), name=name, description=fn.__doc__)
