"""Administration tools: multi-binary selection (see TODO.md phase 6).

`select_binary`/`load_binary` set an explicit selection in binary_context,
which every read/write tool's `get_current_view()` call then prefers over
the GUI's currently-focused tab (Phase 3's original fallback behavior).
Always registered -- there's no gating setting for administration, same as
the read tools.
"""

from pathlib import Path

import binaryninja

from . import binary_context
from .concurrency import log_tool_call, serialized


@serialized
def select_binary(index: int) -> dict:
    """Select which open binary subsequent tool calls operate on, by its
    index into program://binaries. Persists until the selected binary is
    closed or select_binary() is called again."""
    bv = binary_context.select_binary(index)
    return {"index": index, "path": bv.file.filename}


@serialized
def load_binary(path: str) -> dict:
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
            return {"index": i, "path": view_path}
    raise RuntimeError(f"opened {resolved!r} but it isn't showing up in program://binaries yet")


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
