import atexit
import sys
import threading
from pathlib import Path

_plugin_dir = Path(__file__).parent.resolve()
_deps = _plugin_dir / ".deps"
if _deps.is_dir() and str(_deps) not in sys.path:
    sys.path.insert(0, str(_deps))

import binaryninja
from binaryninja import Settings

from .core.logging import get_logger
from .core.settings import register_setting

from . import api

logger = get_logger("mcp_server")

register_setting(
    "mcp_server.enabled",
    "Start the MCP server when Binary Ninja loads (GUI: also controls autostart)",
    True,
)
register_setting(
    "mcp_server.bind_address",
    "Address the MCP HTTP server binds to",
    "127.0.0.1",
)
register_setting(
    "mcp_server.http_port",
    "Port for the MCP HTTP server",
    9090,
)
register_setting(
    "mcp_server.api_key",
    "API key required to call the MCP server; auto-generated on first run, clear to disable auth",
    "",
)
register_setting(
    "mcp_server.api_key_generated",
    "Internal: whether an API key has already been auto-generated (do not edit)",
    False,
)
register_setting(
    "mcp_server.write_enabled",
    "Enable safe write tools (rename, comments, types, structs)",
    True,
)
register_setting(
    "mcp_server.destructive_write_enabled",
    "Enable destructive write tools (patch_asm, edit_hex)",
    False,
)
register_setting(
    "mcp_server.undo_enabled",
    "Enable undo_action; reverts BN's undo stack, including the user's own manual "
    "edits, not just tool-made changes",
    False,
)
register_setting(
    "mcp_server.scripting_enabled",
    "Enable scripting tools (execute_script, load_script, search_docs, read_logs, create_snippet)",
    False,
)
register_setting(
    "mcp_server.debugging_enabled",
    "Enable debugger control tools (launch, breakpoints, step, resume, kill)",
    False,
)
register_setting(
    "mcp_server.screenshot_enabled",
    "Enable capture_screenshot",
    False,
)
register_setting(
    "mcp_server.debug_logging",
    "Log every MCP tool call (timestamp, tool, params) to ~/.binaryninja/logs/mcp_server.log",
    False,
)
register_setting(
    "mcp_server.echo_target_enabled",
    "Prepend a '#binary  index  path' line to read/list tool output identifying which "
    "binary the call ran against -- the bn CLI reroutes this line to stderr so piped "
    "stdout stays clean",
    True,
)


def _start_command():
    try:
        api.start_server()
        status = api.get_server_status()
        logger.info(f"MCP Server: listening on http://{status.host}:{status.port}")
    except Exception as e:
        logger.error(f"failed to start MCP server: {e}")


def _stop_command():
    api.stop_server()
    logger.info("MCP Server: stopped")


def _copy_api_key_command():
    key = api.ensure_api_key()
    try:
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        clipboard.setText(key)
        logger.info("MCP Server: API key copied to clipboard" if key else "MCP Server: auth is disabled (no key set)")
    except Exception as e:
        logger.warning(f"could not access clipboard: {e}")
        logger.info(f"MCP Server: API key: {key or '(auth disabled)'}")


def _install_mcp_clients_command():
    """Run scripts/install_mcp_clients.py in-process (see its main(argv)
    docstring) against this instance's own URL/API key, so registering
    Claude Code/Codex/OpenCode/DeepAgents and linking the `bn` CLI is a
    single menu click instead of a manual terminal invocation. Doesn't
    require the server to already be running -- get_effective_endpoint()
    and ensure_api_key() both work off configured settings either way.

    Runs on a worker thread, not the calling (main/UI) thread: unlike the
    other MCP Server commands, this one shells out to each client's own CLI
    (`claude`, `codex`, `opencode`), which can take a perceptible moment and
    would otherwise freeze the GUI for it. Safe to do here specifically
    because nothing on this path touches binaryninjaui -- just Settings,
    subprocess, the filesystem, and our own logger, all thread-safe to call
    off the main thread, unlike actual UI API calls.
    """

    def run():
        import contextlib
        import io

        from .scripts import install_mcp_clients

        host, port = api.get_effective_endpoint()
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"  # a wildcard bind isn't a valid client-side target -- clients run locally
        url = f"http://{host}:{port}/mcp"
        key = api.ensure_api_key()
        argv = ["--url", url] + (["--api-key", key] if key else ["--no-auth"])

        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = install_mcp_clients.main(argv)
        except SystemExit as e:
            # argparse's own parser.error() calls sys.exit(2) -- shouldn't
            # happen with args built here, but never let that tear down the
            # whole BN process if it somehow does.
            code = e.code if isinstance(e.code, int) else 1

        for line in out.getvalue().splitlines():
            if line.strip():
                (logger.error if line.startswith("[error]") else logger.info)(f"MCP Server: {line}")
        if code == 0:
            logger.info("MCP Server: client install finished")
        else:
            logger.error("MCP Server: client install finished with errors -- see above")

    threading.Thread(target=run, name="mcp-server-install-clients", daemon=True).start()


def _register_gui_commands():
    # PluginCommand is BinaryView-scoped in BN's core (its C signature takes
    # a BNBinaryView*), so BN only shows/enables those commands when a
    # binary is open. The MCP server's lifecycle is global, not tied to any
    # binary, so it needs binaryninjaui's UIAction/Menu instead -- those are
    # always available, with or without an open BinaryView.
    from binaryninjaui import Menu, UIAction, UIActionHandler

    commands = (
        ("MCP Server\\Start Server", _start_command),
        ("MCP Server\\Stop Server", _stop_command),
        ("MCP Server\\Copy API Key", _copy_api_key_command),
        ("MCP Server\\Install MCP Clients", _install_mcp_clients_command),
    )
    for name, callback in commands:
        UIAction.registerAction(name)
        UIActionHandler.globalActions().bindAction(name, UIAction(lambda context, cb=callback: cb()))
        Menu.mainMenu("Plugins").addAction(name, "MCP Server")


if binaryninja.core_ui_enabled():
    _register_gui_commands()

if Settings().get_bool("mcp_server.enabled"):
    try:
        api.start_server()
        status = api.get_server_status()
        logger.info(f"MCP server autostarted on http://{status.host}:{status.port}")
    except Exception as e:
        logger.error(f"MCP server autostart failed: {e}")

atexit.register(api.stop_server)
