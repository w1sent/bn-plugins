"""GUI utility tools: capture_screenshot (see TODO.md "MCP Tools (GUI
utility)"). Gated by `mcp_server.screenshot_enabled` (default off).

Like binary_context, all binaryninjaui/Qt access here is marshalled onto
BN's main thread via `execute_on_main_thread_and_wait` -- calling Qt
directly from the MCP server's own thread previously crashed BN with a
SIGSEGV.
"""

import binaryninja
from mcp.server.fastmcp import Image

from .binary_context import _require_gui
from .concurrency import log_tool_call, serialized


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
