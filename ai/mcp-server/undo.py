"""Undo tool: reverts BN's native undo stack (see TODO.md "MCP Tools
(undo)"). Gated by its own setting, `mcp_server.undo_enabled` (default
off) -- separate from `mcp_server.write_enabled` because this reverts the
undo stack wholesale, including manual edits the human made in the GUI, not
just changes the AI/tools made. Off by default so an agent can't silently
discard the user's own work.
"""

import binaryninja

from .binary_context import get_current_view
from .concurrency import log_tool_call, serialized


@serialized
def undo_action(steps: int = 1) -> dict:
    """Revert the last `steps` change(s) to the current binary via Binary
    Ninja's native undo mechanism. This affects the whole undo stack --
    including manual edits made by the user in the GUI, not just changes
    made by MCP tools -- so use with care."""
    bv = get_current_view()
    for _ in range(steps):
        bv.file.undo()
    binaryninja.log_info(f"[mcp-server] undo_action: reverted {steps} step(s)")
    return {"steps": steps}


def register(mcp) -> None:
    mcp.add_tool(log_tool_call(undo_action), name="undo_action", description=undo_action.__doc__)
