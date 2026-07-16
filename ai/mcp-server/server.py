"""HTTP transport lifecycle for the Binary Ninja MCP server.

This module owns exactly one `FastMCP` instance and the uvicorn server
serving it, plus API-key enforcement. Tool/resource/prompt registration
happens elsewhere (later phases) via the `.mcp` attribute -- this module
only knows how to start and stop the transport cleanly.
"""

import asyncio
import logging
import secrets
import threading

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import PlainTextResponse

from .core.logging import get_logger

logger = get_logger("mcp_server")

_SERVER_NAME = "Binary Ninja"

# `FastMCP.__init__` unconditionally calls mcp's `configure_logging()`, which
# runs `logging.basicConfig(handlers=[RichHandler(stderr=True)])` -- i.e. it
# installs a handler on the *root* logger for the whole process the first
# time a FastMCP instance is created. BN's scripting console renders any
# stderr output as an error block, so plain INFO messages ("session manager
# started") show up looking like errors. `basicConfig` is a no-op if the
# root logger already has a handler, so pre-seeding one here (once, at
# import time, before any FastMCP() is constructed) keeps that entirely out
# of BN's global logging, without needing to touch FastMCP's own log_level.
if not logging.getLogger().handlers:
    logging.getLogger().addHandler(logging.NullHandler())

# Redirect the "mcp"/"uvicorn" logger families into our own per-plugin log
# file instead: quiet enough to skip routine INFO chatter, but real
# warnings/errors are still captured somewhere, not just silently dropped.
for _name in ("mcp", "uvicorn", "uvicorn.error", "uvicorn.access", "sse_starlette"):
    _lib_logger = logging.getLogger(_name)
    _lib_logger.handlers = list(logger.handlers)
    _lib_logger.propagate = False
    _lib_logger.setLevel(logging.WARNING)


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


class _AuthMiddleware:
    """Bare ASGI middleware enforcing a bearer API key.

    Wrapping the ASGI app directly (rather than a Starlette
    BaseHTTPMiddleware) so lifespan events pass through untouched --
    FastMCP's streamable-http app starts its session manager's task group
    from a lifespan handler, which BaseHTTPMiddleware doesn't forward.
    """

    def __init__(self, app, get_api_key):
        self._app = app
        self._get_api_key = get_api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        if scope.get("path") == "/health":
            await PlainTextResponse("ok")(scope, receive, send)
            return

        expected = self._get_api_key()
        if expected:
            headers = dict(scope.get("headers") or [])
            auth = headers.get(b"authorization", b"").decode("latin-1")
            token = auth[len("Bearer ") :] if auth.startswith("Bearer ") else ""
            if not secrets.compare_digest(token, expected):
                await PlainTextResponse("Unauthorized", status_code=401)(scope, receive, send)
                return

        await self._app(scope, receive, send)


class MCPServer:
    """Owns the HTTP transport lifecycle for one FastMCP instance.

    `get_api_key` is called on every request (not read once at construction)
    so toggling/rotating the key via settings takes effect without a
    restart.
    """

    def __init__(self, host: str, port: int, get_api_key=lambda: None):
        self.host = host
        self.port = port
        self._get_api_key = get_api_key
        self.mcp = FastMCP(_SERVER_NAME, host=host, port=port)

        self._thread = None
        self._uvicorn_server = None
        self._ready = threading.Event()
        self._start_error = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, timeout: float = 5.0) -> None:
        with self._lock:
            if self.running:
                return
            self._ready.clear()
            self._start_error = None
            self._thread = threading.Thread(target=self._run, name="mcp-server", daemon=True)
            self._thread.start()

        if not self._ready.wait(timeout=timeout):
            raise TimeoutError("MCP server did not start within timeout")
        if self._start_error:
            raise self._start_error
        logger.info(f"MCP server listening on http://{self.host}:{self.port}")

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            server = self._uvicorn_server
            thread = self._thread
        if not server or not thread or not thread.is_alive():
            return
        server.should_exit = True
        thread.join(timeout=timeout)
        logger.info("MCP server stopped")

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        except Exception as exc:
            self._start_error = exc
            self._ready.set()
            logger.error(f"MCP server failed: {exc}")
        finally:
            loop.close()

    async def _serve(self):
        app = _AuthMiddleware(self.mcp.streamable_http_app(), self._get_api_key)
        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="warning")
        server = uvicorn.Server(config)
        self._uvicorn_server = server

        try:
            # Replicates the setup Server._serve() normally does before
            # startup() -- we call startup()/main_loop()/shutdown() directly
            # instead of _serve()/serve() so stop() can trigger a clean
            # shutdown from another thread via should_exit.
            if not config.loaded:
                config.load()
            server.lifespan = config.lifespan_class(config)

            await server.startup()
        except (Exception, SystemExit) as exc:
            self._start_error = RuntimeError(f"failed to bind {self.host}:{self.port}: {exc}")
            self._ready.set()
            return

        if server.should_exit:
            self._start_error = RuntimeError(f"failed to bind {self.host}:{self.port}")
            self._ready.set()
            return

        self._ready.set()
        await server.main_loop()
        await server.shutdown()
