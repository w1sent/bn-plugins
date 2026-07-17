"""Destructive write tools: patch_asm, edit_hex.

Gated by `mcp_server.destructive_write_enabled` (default off) -- unlike the
safe-write tier, these overwrite the binary's actual bytes and can corrupt
the file/analysis.

`patch_c` (TODO.md phase 7) is deliberately NOT implemented: Binary Ninja's
Python API has no headless C-compile facility. The GUI's `CompileDialog`
(binaryninjaui.CompileDialog) looks promising but its compile step is wired
to an internal button's Qt signal, not a public method -- calling `.accept()`
directly closes the dialog without actually compiling (confirmed live:
`getBytes()` came back empty). Driving it would require poking at private
widget internals, which is unsupported API surface. Revisit if a public,
non-interactive compile entry point appears in a future BN version.
"""

from typing import Union

import binaryninja

from .binary_context import get_current_view
from .concurrency import log_tool_call, serialized
from .reading import _parse_addr


@serialized
def patch_asm(addr: Union[int, str], assembly: str) -> dict:
    """Assemble `assembly` for the current binary's architecture and write
    the resulting bytes at `addr`, overwriting whatever was there. The new
    instruction(s) may be a different length than what they replace."""
    bv = get_current_view()
    a = _parse_addr(addr)
    new_bytes = bv.arch.assemble(assembly, a)
    old_bytes = bv.read(a, len(new_bytes))
    bv.write(a, new_bytes)
    binaryninja.log_info(f"[mcp-server] patch_asm @ {hex(a)}: {old_bytes.hex()} -> {new_bytes.hex()} ({assembly!r})")
    return {"address": hex(a), "old_bytes": old_bytes.hex(), "new_bytes": new_bytes.hex()}


@serialized
def edit_hex(addr: Union[int, str], hex: str) -> dict:
    """Overwrite the binary's bytes at `addr` with raw hex (e.g. "9090")."""
    bv = get_current_view()
    a = _parse_addr(addr)
    new_bytes = bytes.fromhex(hex)
    old_bytes = bv.read(a, len(new_bytes))
    bv.write(a, new_bytes)
    addr_str = f"0x{a:x}"
    binaryninja.log_info(f"[mcp-server] edit_hex @ {addr_str}: {old_bytes.hex()} -> {new_bytes.hex()}")
    return {"address": addr_str, "old_bytes": old_bytes.hex(), "new_bytes": new_bytes.hex()}


_TOOLS = (
    (patch_asm, "patch_asm"),
    (edit_hex, "edit_hex"),
)


def register(mcp) -> None:
    for fn, name in _TOOLS:
        mcp.add_tool(log_tool_call(fn), name=name, description=fn.__doc__)
