"""Local connection file the `bn` CLI reads to find a running server with
zero manual setup -- see ADR-0038's "Server discovery" section. Written on
server start, removed on stop, at a fixed per-user path, so a fresh CLI
process (no persistent state of its own, no prior handshake to remember)
can find host/port/API key without configuration in the common case: BN
and the CLI running on the same machine.

Not the only way to point the CLI at a server -- an explicit --server flag
or BN_MCP_URL/BN_MCP_API_KEY env var both take precedence over this file
(the CLI's job, not this module's) for a remote BN or any other
non-default topology.

The path itself is overridable via BINJA_MCP_CONNECTION_FILE -- exists so
tests/run.py's own start_server()/stop_server() calls (a second, independent
process exercising the real code against a throwaway test port) write to an
isolated file instead of silently overwriting *and then deleting* a real,
concurrently-running BN instance's connection info out from under it. That
collision isn't hypothetical: it happened during this plugin's own
development, more than once, including breaking `bn health` for an
otherwise perfectly healthy server (see the fix that added this override).
"""

import json
import os
from pathlib import Path
from typing import Optional

_PATH = Path(os.environ["BINJA_MCP_CONNECTION_FILE"]) if os.environ.get("BINJA_MCP_CONNECTION_FILE") else (
    Path.home() / ".cache" / "binja-mcp" / "server.json"
)


def path() -> Path:
    return _PATH


def write(host: str, port: int, api_key: str) -> None:
    """Persist the running server's connection info, replacing any
    previous file (e.g. left behind by a prior run that didn't shut down
    cleanly). 0600 permissions -- this file holds a live API key."""
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"host": host, "port": port, "api_key": api_key, "pid": os.getpid()}
    _PATH.write_text(json.dumps(payload))
    _PATH.chmod(0o600)


def remove() -> None:
    """Remove the connection file, but only if it still describes *this*
    process. The file path isn't scoped per server instance -- a second,
    independent process calling start_server()/stop_server() against a
    different port (e.g. a test harness run alongside a real, separately
    -running BN) would otherwise delete a live server's connection info
    out from under it just by stopping its own, unrelated server. Confirmed
    live: exactly this happened during development, when test scripts'
    stop_server() calls repeatedly deleted the real BN server's file."""
    data = read()
    if data is not None and data.get("pid") != os.getpid():
        return
    _PATH.unlink(missing_ok=True)


def read() -> Optional[dict]:
    """Best-effort read, for in-process Python callers (tests, other
    plugins) -- not used by the `bn` CLI itself, which is a standalone
    script with no import access to this package and carries its own copy
    of this same small amount of parsing logic."""
    try:
        return json.loads(_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
