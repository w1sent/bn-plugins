"""Administration tools: multi-binary selection (see TODO.md phase 6),
plus analysis control (reanalyze/analysis_status).

`select_binary`/`load_binary` set an explicit selection in binary_context,
which every read/write tool's `get_current_view()` call then prefers over
the GUI's currently-focused tab (Phase 3's original fallback behavior).
`save_all` is unrelated to selection -- it saves every open binary, not
just the current one. Always registered -- there's no gating setting for
administration, same as the read tools.

`reanalyze`/`analysis_status` need no job registry the way scripting.py's
async execute_script does: BN's own `update_analysis()` is already
asynchronous on BN's own background worker threads once triggered, and
`BinaryView.analysis_progress` is a native, already-existing poll target --
there's no arbitrary long-running Python code here that needs a thread of
ours to escape the tool-call lock.
"""

from pathlib import Path

import binaryninja
from binaryninja.enums import AnalysisState
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


@serialized
def reanalyze(wait: bool = True) -> CallToolResult:
    """Trigger a full re-analysis of the current binary (same as BN's GUI
    "Reanalyze"): every function is reprocessed from scratch, catching code
    a patch or other change revealed that BN's own incremental analysis
    wouldn't otherwise pick up on its own.

    Defaults to blocking until analysis finishes -- matching the server's
    normal serialized execution (other tool calls wait too), which can be a
    while on a large binary, so pass wait=False to instead trigger analysis
    on BN's own background worker threads and return immediately. Poll
    analysis_status() for progress either way."""
    bv = binary_context.get_current_view()
    bv.reanalyze()
    if wait:
        bv.update_analysis_and_wait()
    else:
        bv.update_analysis()
    progress = bv.analysis_progress
    meta = {"path": bv.file.filename, "waited": wait, "state": progress.state.name}
    return tool_result(render_kv(meta), meta)


@serialized
def analysis_status() -> CallToolResult:
    """Report the current binary's analysis progress -- state/count/total
    from BN's own AnalysisProgress -- e.g. to poll after
    reanalyze(wait=False)."""
    bv = binary_context.get_current_view()
    progress = bv.analysis_progress
    done = progress.state in (AnalysisState.IdleState, AnalysisState.HoldState)
    meta = {"state": progress.state.name, "count": progress.count, "total": progress.total, "done": done}
    return tool_result(render_kv(meta), meta)


def _program_binaries() -> dict:
    views = binary_context.list_available_views()
    selected = binary_context.get_selected_view()
    return {
        "binaries": [
            {"index": i, "path": path, "selected": bv is selected} for i, (bv, path) in enumerate(views)
        ]
    }


def _binary_selected() -> dict:
    # "Nothing open/selected yet" is normal state for this resource, not a
    # failure -- letting NoBinaryOpenError propagate makes FastMCP's
    # read_resource() log a full ERROR-level traceback (it unconditionally
    # logger.exception()s any exception a resource raises) on every read
    # while BN has no binary open, e.g. every `bn` CLI call's
    # ensure_binary_target() pre-flight check. Tools that actually need a
    # BinaryView to operate on still get a real error from
    # get_current_view() itself -- this only softens the read-only status
    # resource.
    try:
        bv = binary_context.get_current_view()
    except binary_context.NoBinaryOpenError:
        return {"path": None, "explicitly_selected": False, "arch": None, "view_type": None}
    is_explicit = binary_context.get_selected_view() is not None
    return {
        "path": bv.file.filename,
        "explicitly_selected": is_explicit,
        "arch": bv.arch.name if bv.arch else None,
        "view_type": bv.view_type,
    }


_HEADLESS_LICENSE_TIERS = ("Ultimate", "Commercial")


def _program_info() -> dict:
    """Static info about the running Binary Ninja instance itself, not any
    particular binary -- currently just enough to know whether headless
    scripting is available under this license. BN's headless API (running
    scripts via a standalone `binaryninja` Python import/CLI invocation,
    with no GUI) is gated to the Ultimate/Commercial license tiers per
    BNGetProduct(); every other tier (Free, Personal, Student, Enterprise
    Client, ...) can only run scripts inside a live GUI session -- see the
    binja-cli skill for why that makes `bn execute-script`/`load-script`/
    `run-snippet` the way to run scripts there instead of a standalone
    headless script."""
    product = binaryninja.core_product()
    headless_supported = bool(product) and any(tier in product for tier in _HEADLESS_LICENSE_TIERS)
    return {"product": product, "headless_supported": headless_supported}


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
    (reanalyze, "reanalyze"),
    (analysis_status, "analysis_status"),
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
    mcp.resource(
        "program://info",
        name="program_info",
        description="Info about the running Binary Ninja instance/license (product, headless script support)",
    )(_program_info)
    mcp.resource("program://plugins", name="program_plugins", description="Installed Binary Ninja plugins")(
        _program_plugins
    )
