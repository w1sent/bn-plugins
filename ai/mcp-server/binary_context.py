"""Resolves "the current binary" that read/write tools operate against.

Explicit selection (via `select_binary`/`load_binary` in administration.py)
takes priority when set; otherwise this falls back to whichever BinaryView
is focused in the GUI's current tab. A selection is automatically dropped
(falling back to the GUI-focused tab again) once its binary is no longer
among the GUI's open tabs -- e.g. the user closed it.

All binaryninjaui access here is marshalled onto BN's main Qt thread via
`execute_on_main_thread_and_wait`: calling UIContext directly from the MCP
server's own background thread previously crashed BN with a SIGSEGV (Qt
widgets aren't thread-safe).
"""

import binaryninja
from binaryninja import BinaryView


class NoBinaryOpenError(RuntimeError):
    pass


_selected_bv: BinaryView = None


def _require_gui() -> None:
    if not binaryninja.core_ui_enabled():
        raise NoBinaryOpenError("no GUI session; binary selection isn't available in headless mode yet")


def list_available_views() -> list:
    """Return [(BinaryView, path)] for every binary currently open as a tab
    in the GUI (the same list `program://binaries`/`select_binary` index
    into)."""
    _require_gui()
    result = {}

    def grab():
        import binaryninjaui as ui

        contexts = ui.UIContext.allContexts()
        result["views"] = list(contexts[0].getAvailableBinaryViews()) if contexts else []

    binaryninja.execute_on_main_thread_and_wait(grab)
    return result.get("views", [])


def select_binary(index: int) -> BinaryView:
    """Explicitly select which open binary subsequent tool calls operate on,
    by its index into `list_available_views()`/`program://binaries`."""
    global _selected_bv
    views = list_available_views()
    if index < 0 or index >= len(views):
        raise ValueError(f"no binary at index {index}; {len(views)} binary(ies) currently open")
    _selected_bv = views[index][0]
    return _selected_bv


def get_selected_view() -> BinaryView:
    """Return the explicitly selected BinaryView, or None if there isn't one
    (or it was closed since being selected)."""
    global _selected_bv
    if _selected_bv is None:
        return None
    if not any(bv is _selected_bv for bv, _ in list_available_views()):
        _selected_bv = None  # the selected binary was closed; fall through
        return None
    return _selected_bv


def get_current_view() -> BinaryView:
    """Return the BinaryView tool calls should operate on: the explicit
    selection if one is set and still open, otherwise whichever BinaryView
    is focused in the GUI's current tab."""
    selected = get_selected_view()
    if selected is not None:
        return selected

    _require_gui()
    result = {}

    def grab():
        import binaryninjaui as ui

        contexts = ui.UIContext.allContexts()
        if not contexts:
            return
        vf = contexts[0].getCurrentViewFrame()
        if vf is None:
            return
        result["bv"] = vf.getCurrentBinaryView()

    binaryninja.execute_on_main_thread_and_wait(grab)
    bv = result.get("bv")
    if bv is None:
        raise NoBinaryOpenError("no binary is currently open in Binary Ninja")
    return bv
