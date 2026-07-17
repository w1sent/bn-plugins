"""Resolves "the current binary" that read (and later write) tools operate
against.

v1 (this phase): there's no explicit multi-binary selection yet -- that's
`select_binary`, added in the administration phase -- so this always falls
back to whichever BinaryView is focused in the GUI's current tab.

All binaryninjaui access here is marshalled onto BN's main Qt thread via
`execute_on_main_thread_and_wait`: calling UIContext directly from the MCP
server's own background thread previously crashed BN with a SIGSEGV (Qt
widgets aren't thread-safe).
"""

import binaryninja
from binaryninja import BinaryView


class NoBinaryOpenError(RuntimeError):
    pass


def get_current_view() -> BinaryView:
    """Return the BinaryView currently focused in the BN GUI's active tab."""
    if not binaryninja.core_ui_enabled():
        raise NoBinaryOpenError("no GUI session; binary selection isn't available in headless mode yet")

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
