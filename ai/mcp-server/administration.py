"""Administration tools: multi-binary selection (see TODO.md phase 6).

`select_binary`/`load_binary` set an explicit selection in binary_context,
which every read/write tool's `get_current_view()` call then prefers over
the GUI's currently-focused tab (Phase 3's original fallback behavior).
`save_all` is unrelated to selection -- it saves every open binary, not
just the current one. Always registered -- there's no gating setting for
administration, same as the read tools.
"""

from pathlib import Path

import binaryninja
from mcp.types import CallToolResult

from . import binary_context
from .concurrency import log_tool_call, serialized
from .rendering import render_kv, render_table, tool_result


@serialized
def select_binary(index: int) -> CallToolResult:
    """Select which open binary subsequent tool calls operate on, by its
    index into program://binaries. Persists until the selected binary is
    closed or select_binary() is called again."""
    bv = binary_context.select_binary(index)
    meta = {"index": index, "path": bv.file.filename}
    return tool_result(render_kv(meta), meta)


@serialized
def load_binary(path: str) -> CallToolResult:
    """Open a binary or .bndb file in the GUI (as a new tab) and select it
    as the current binary for subsequent tool calls."""
    binary_context._require_gui()
    resolved = str(Path(path).expanduser())
    result = {}

    def do_open():
        import binaryninjaui as ui

        c = ui.UIContext.allContexts()[0]
        c.openFilename(resolved)
        result["ok"] = True

    binaryninja.execute_on_main_thread_and_wait(do_open)
    if not result.get("ok"):
        raise RuntimeError(f"failed to open {resolved!r} in the GUI")

    views = binary_context.list_available_views()
    for i, (_, view_path) in enumerate(views):
        if view_path == resolved:
            binary_context.select_binary(i)
            meta = {"index": i, "path": view_path}
            return tool_result(render_kv(meta), meta)
    raise RuntimeError(f"opened {resolved!r} but it isn't showing up in program://binaries yet")


@serialized
def save_all() -> CallToolResult:
    """Save every open binary's analysis database. Binaries not yet backed
    by a .bndb get one created next to the original file (path + ".bndb");
    binaries that already have one get a snapshot saved to it."""
    saved = []
    for bv, path in binary_context.list_available_views():
        if bv.file.has_database:
            dest = bv.file.filename
            ok = bv.save_auto_snapshot()
        else:
            dest = f"{path}.bndb"
            ok = bv.create_database(dest)
        saved.append({"path": path, "database": dest, "saved": bool(ok)})
    meta = {"saved": saved}
    text = render_table(saved, fields=["path", "database", "saved"])
    return tool_result(text, meta)


def _program_binaries() -> dict:
    views = binary_context.list_available_views()
    selected = binary_context.get_selected_view()
    return {
        "binaries": [
            {"index": i, "path": path, "selected": bv is selected} for i, (bv, path) in enumerate(views)
        ]
    }


def _binary_selected() -> dict:
    bv = binary_context.get_current_view()
    is_explicit = binary_context.get_selected_view() is not None
    return {
        "path": bv.file.filename,
        "explicitly_selected": is_explicit,
        "arch": bv.arch.name if bv.arch else None,
        "view_type": bv.view_type,
    }


def _program_plugins() -> dict:
    rm = binaryninja.RepositoryManager()
    plugins = []
    for repo in rm.repositories:
        for p in repo.plugins:
            if not p.installed:
                continue
            plugins.append(
                {
                    "name": p.name,
                    "enabled": bool(p.enabled),
                    "version": p.version,
                    "path": p.path,
                }
            )
    return {"plugins": plugins}


_TOOLS = (
    (select_binary, "select_binary"),
    (load_binary, "load_binary"),
    (save_all, "save_all"),
)


def register(mcp) -> None:
    for fn, name in _TOOLS:
        mcp.add_tool(log_tool_call(fn), name=name, description=fn.__doc__)

    mcp.resource(
        "binary://selected", name="binary_selected", description="The currently selected/focused binary"
    )(_binary_selected)
    mcp.resource(
        "program://binaries", name="program_binaries", description="All binaries currently open in the GUI"
    )(_program_binaries)
    mcp.resource("program://plugins", name="program_plugins", description="Installed Binary Ninja plugins")(
        _program_plugins
    )
