"""Debugger control tools (see TODO.md phase 8 -- lowest priority, "a second
plugin's surface"). Gated by `mcp_server.debugging_enabled` (default off).

Built on BN's own debugger plugin (`binaryninja.debugger.DebuggerController`,
constructed fresh per call from `get_current_view()` -- confirmed live that
two instances built from the same BinaryView compare equal and share the
same underlying debug session, so there's no need to cache one ourselves).

Important: for PIE binaries, the analysis view's addresses get rebased to
match the live process once a debug session is running -- an address you
read *before* `launch()` (e.g. from get_function) will not match where that
code actually ends up at runtime. Confirmed live: setting a breakpoint on
the pre-launch address caused the process to run to completion, missing it
entirely; setting it on the address re-read *after* `launch()` hit
correctly. Always re-fetch the address you want to break on after
`launch()`, not before.
"""

from typing import Union

import binaryninja
from binaryninja.debugger import DebuggerController
from mcp.types import CallToolResult

from .binary_context import get_current_view
from .concurrency import log_tool_call, serialized
from .reading import _parse_addr
from .rendering import render_kv, tool_result


def _controller() -> DebuggerController:
    return DebuggerController(get_current_view())


def _status_dict(dc: DebuggerController) -> dict:
    return {"ip": hex(dc.ip), "running": dc.running, "stop_reason": dc.stop_reason_str}


def _status(dc: DebuggerController) -> CallToolResult:
    meta = _status_dict(dc)
    return tool_result(render_kv(meta), meta)


@serialized
def launch() -> CallToolResult:
    """Launch the current binary under BN's debugger. Stops at an initial
    breakpoint (the process entry point) before any code runs -- call
    resume() to continue from there. Re-fetch addresses (e.g. via
    get_function) after this call before setting breakpoints: PIE binaries
    get rebased to their live load address once the process is running."""
    dc = _controller()
    dc.launch_and_wait()
    return _status(dc)


@serialized
def set_breakpoint(addr: Union[int, str]) -> CallToolResult:
    """Set a breakpoint at an address. Use an address re-fetched after
    launch() for a PIE binary, not one read beforehand (see module note)."""
    dc = _controller()
    a = _parse_addr(addr)
    dc.add_breakpoint(a)
    binaryninja.log_info(f"[mcp-server] set_breakpoint @ {hex(a)}")
    meta = {"address": hex(a)}
    return tool_result(render_kv(meta), meta)


@serialized
def resume() -> CallToolResult:
    """Resume execution until the next breakpoint, signal, or process exit."""
    dc = _controller()
    dc.go_and_wait()
    return _status(dc)


@serialized
def run_until(addr: Union[int, str]) -> CallToolResult:
    """Run until execution reaches a specific address (a one-shot
    breakpoint), or until it stops for another reason first."""
    dc = _controller()
    a = _parse_addr(addr)
    dc.run_to_and_wait(a)
    return _status(dc)


@serialized
def step_into() -> CallToolResult:
    """Single-step, stepping into any called function."""
    dc = _controller()
    dc.step_into_and_wait()
    return _status(dc)


@serialized
def step_over() -> CallToolResult:
    """Single-step, stepping over any called function."""
    dc = _controller()
    dc.step_over_and_wait()
    return _status(dc)


@serialized
def step_return() -> CallToolResult:
    """Run until the current function returns to its caller."""
    dc = _controller()
    dc.step_return_and_wait()
    return _status(dc)


@serialized
def kill_process() -> CallToolResult:
    """Stop (kill) the debugged process."""
    dc = _controller()
    dc.quit_and_wait()
    meta = {"running": dc.running}
    return tool_result(render_kv(meta), meta)


@serialized
def restart() -> CallToolResult:
    """Restart the debugged process from the beginning."""
    dc = _controller()
    dc.restart_and_wait()
    return _status(dc)


_TOOLS = (
    (launch, "launch"),
    (set_breakpoint, "set_breakpoint"),
    (resume, "resume"),
    (run_until, "run_until"),
    (step_into, "step_into"),
    (step_over, "step_over"),
    (step_return, "step_return"),
    (kill_process, "kill_process"),
    (restart, "restart"),
)


def register(mcp) -> None:
    for fn, name in _TOOLS:
        mcp.add_tool(log_tool_call(fn), name=name, description=fn.__doc__)
