"""GUI utility tools: capture_screenshot (see TODO.md "MCP Tools (GUI
utility)"). Gated by `mcp_server.screenshot_enabled` (default off).

Also owns the status bar indicator (a small permanent label, "MCP :<port>",
in Binary Ninja's main window status bar) that reflects whether the MCP
server is currently running -- shown while running, hidden entirely
otherwise. This is not gated by any setting: it just mirrors server state,
same as the "Start/Stop Server" menu commands.

Like binary_context, all binaryninjaui/Qt access here is marshalled onto
BN's main thread via `execute_on_main_thread_and_wait` -- calling Qt
directly from the MCP server's own thread previously crashed BN with a
SIGSEGV.
"""

import binaryninja
from mcp.server.fastmcp import Image

from .binary_context import _require_gui
from .concurrency import log_tool_call, serialized

_status_widget = None


def _status_bar_indicator(mw):
    """Return the shared status bar QLabel, creating it on first use.
    Recreates it if the previous one was torn down with its window (e.g.
    BN's main window was recreated), which raises RuntimeError on access."""
    global _status_widget
    if _status_widget is not None:
        try:
            _status_widget.isVisible()
            return _status_widget
        except RuntimeError:
            _status_widget = None

    from PySide6.QtWidgets import QLabel

    _status_widget = QLabel()
    _status_widget.setVisible(False)
    mw.statusBar().addPermanentWidget(_status_widget)
    return _status_widget


def set_server_running(running: bool, host: str = None, port: int = None) -> None:
    """Update the status bar indicator to reflect whether the MCP server is
    running. No-op outside a GUI session (e.g. headless mode)."""
    if not binaryninja.core_ui_enabled():
        return

    def do_update():
        import binaryninjaui as ui

        contexts = ui.UIContext.allContexts()
        if not contexts:
            return
        mw = contexts[0].mainWindow()
        if mw is None:
            return
        widget = _status_bar_indicator(mw)
        if running:
            widget.setText(f"MCP :{port}" if port else "MCP")
            widget.setToolTip(f"Binary Ninja MCP server running on {host}:{port}")
        widget.setVisible(running)

    binaryninja.execute_on_main_thread_and_wait(do_update)


@serialized
def capture_screenshot() -> Image:
    """Capture a screenshot of the whole Binary Ninja window, returned
    inline as an image. Useful when you want to show the user (or refer
    back to) exactly what's currently on screen."""
    _require_gui()
    result = {}

    def do_capture():
        import binaryninjaui as ui
        from PySide6.QtCore import QBuffer, QIODevice

        contexts = ui.UIContext.allContexts()
        if not contexts:
            return
        mw = contexts[0].mainWindow()
        if mw is None:
            return
        pixmap = mw.grab()
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buf, "PNG")
        result["data"] = bytes(buf.data())

    binaryninja.execute_on_main_thread_and_wait(do_capture)
    data = result.get("data")
    if not data:
        raise RuntimeError("could not capture the Binary Ninja window")
    return Image(data=data, format="png")


def register(mcp) -> None:
    mcp.add_tool(log_tool_call(capture_screenshot), name="capture_screenshot", description=capture_screenshot.__doc__)
