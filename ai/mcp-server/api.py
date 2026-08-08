"""mcp_server.api -- canonical API for the Binary Ninja MCP server.

    start_server(*, host=None, port=None) -> MCPServer
    stop_server(server=None)
    get_server_status() -> ServerStatus
    get_effective_endpoint() -> tuple[str, int]
    ensure_api_key() -> str

The server is process-global (not bound to a particular BinaryView) --
which binary its tools operate on is chosen separately via the
administration tools (`select_binary`, added in a later phase), not by
which BinaryView happened to be passed to `start_server`.
"""

import threading
from dataclasses import dataclass
from typing import Optional

from binaryninja import Settings

from . import administration, connection_file, debugging, gui, listing, patching, prompts, reading, scripting, undo, writing
from .core.logging import get_logger
from .server import MCPServer, generate_api_key

logger = get_logger("mcp_server")

_ENABLED_KEY = "mcp_server.enabled"
_HOST_KEY = "mcp_server.bind_address"
_PORT_KEY = "mcp_server.http_port"
_API_KEY_KEY = "mcp_server.api_key"
_API_KEY_GENERATED_KEY = "mcp_server.api_key_generated"

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 9090

_lock = threading.Lock()
_server: Optional[MCPServer] = None


@dataclass
class ServerStatus:
    running: bool
    host: Optional[str] = None
    port: Optional[int] = None
    auth_enabled: bool = False


def _current_api_key() -> str:
    return Settings().get_string(_API_KEY_KEY) or ""


def ensure_api_key() -> str:
    """Return the current API key, generating and persisting one on the
    first-ever run. Once generated, the key persists across restarts; if
    the user later clears it, that's treated as an intentional opt-out of
    auth, not a state to regenerate from."""
    settings = Settings()
    if not settings.get_bool(_API_KEY_GENERATED_KEY):
        key = generate_api_key()
        settings.set_string(_API_KEY_KEY, key)
        settings.set_bool(_API_KEY_GENERATED_KEY, True)
        logger.info("generated a new MCP server API key")
        return key
    return _current_api_key()


def _register_tools(mcp, settings) -> None:
    """Register tool categories enabled by settings onto `mcp`. Called once
    per server start, before the transport comes up -- a category disabled
    at this point is never registered, not merely blocked at call time, so
    an MCP client never sees a tool it isn't allowed to use. Toggling a
    setting takes effect on the next server restart, not live."""
    reading.register(mcp)
    listing.register(mcp)
    administration.register(mcp)
    prompts.register(mcp)
    if settings.get_bool("mcp_server.write_enabled"):
        writing.register(mcp)
    if settings.get_bool("mcp_server.destructive_write_enabled"):
        patching.register(mcp)
    if settings.get_bool("mcp_server.undo_enabled"):
        undo.register(mcp)
    if settings.get_bool("mcp_server.screenshot_enabled"):
        gui.register(mcp)
    if settings.get_bool("mcp_server.debugging_enabled"):
        debugging.register(mcp)
    if settings.get_bool("mcp_server.scripting_enabled"):
        scripting.register(mcp)


def start_server(*, host: Optional[str] = None, port: Optional[int] = None) -> MCPServer:
    """Start the MCP HTTP server if it isn't already running."""
    global _server
    settings = Settings()
    with _lock:
        if _server is not None and _server.running:
            # Re-write the connection file even though nothing about the
            # server itself changed: it can go missing or get overwritten
            # out from under a long-running server by something else on the
            # same machine writing the same fixed path (e.g. tests/run.py
            # against a real BN instance, before BINJA_MCP_CONNECTION_FILE
            # existed -- confirmed live), and calling start_server() again
            # (e.g. clicking "Start Server" when it's already running) is
            # the natural way a user tries to repair that. Cheap and
            # idempotent, so doing it unconditionally here beats requiring
            # an actual stop/start cycle to fix a `bn health` that can't
            # find the server anymore despite it being perfectly healthy.
            connection_file.write(_server.host, _server.port, _current_api_key())
            return _server

        ensure_api_key()
        resolved_host = host or settings.get_string(_HOST_KEY) or _DEFAULT_HOST
        resolved_port = port or settings.get_integer(_PORT_KEY) or _DEFAULT_PORT

        _server = MCPServer(resolved_host, resolved_port, get_api_key=_current_api_key)
        _register_tools(_server.mcp, settings)
        _server.start()
        gui.set_server_running(True, resolved_host, resolved_port)
        connection_file.write(resolved_host, resolved_port, _current_api_key())
        return _server


def stop_server(server: Optional[MCPServer] = None) -> None:
    """Stop the given server, or the process-global one if none is passed."""
    global _server
    with _lock:
        target = server if server is not None else _server
        if target is None:
            return
        target.stop()
        if target is _server:
            _server = None
        gui.set_server_running(False)
        connection_file.remove()


def get_effective_endpoint() -> tuple[str, int]:
    """Host/port an MCP client should target right now: the running
    server's actual bind address/port if one is up, otherwise whatever a
    start_server() call would use (configured settings, falling back to
    defaults) -- same resolution as start_server() itself, without actually
    starting anything. For callers that need a URL to hand a client
    regardless of whether the server has been started yet, e.g. the
    "Install MCP Clients" GUI command."""
    with _lock:
        if _server is not None and _server.running:
            return _server.host, _server.port
    settings = Settings()
    host = settings.get_string(_HOST_KEY) or _DEFAULT_HOST
    port = settings.get_integer(_PORT_KEY) or _DEFAULT_PORT
    return host, port


def get_server_status() -> ServerStatus:
    with _lock:
        if _server is None or not _server.running:
            return ServerStatus(running=False)
        return ServerStatus(
            running=True,
            host=_server.host,
            port=_server.port,
            auth_enabled=bool(_current_api_key()),
        )


def help() -> None:
    print(__doc__)
