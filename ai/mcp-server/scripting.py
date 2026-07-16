"""Scripting tools -- execute_script, load_script, search_docs, read_logs,
create_snippet, plus async job control (get_script_status/cancel_script).

Gated by `mcp_server.scripting_enabled` (default off): `execute_script` and
`load_script` run arbitrary Python inside the BN process, which is the
whole point (using the MCP server as a stand-in for BN's commercial-only
headless mode when testing plugins) but also real code execution, so it's
opt-in. Only `register()` is called from api.py when the setting is on --
everything else here is plain functions, importable/testable on their own.
"""

import contextlib
import importlib
import inspect
import io
import pkgutil
import re
import sys
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import binaryninja
from binaryninja.enums import LogLevel

from .concurrency import log_tool_call, serialized
from .core.logging import get_logger

logger = get_logger("mcp_server")


class _ThreadLocalStream:
    """A sys.stdout/stderr replacement that only redirects the *calling
    thread's* output into a per-thread buffer, falling through to the real
    stream for every other thread.

    Plain `contextlib.redirect_stdout` swaps `sys.stdout` process-wide --
    since async script jobs run on their own thread while the rest of BN
    (and other tool calls) keep running concurrently, that would vacuum up
    unrelated threads' output for the duration of the script. This proxy is
    installed once, globally, and thereafter every write() call looks up
    the calling thread's own buffer (if any) rather than a shared one.
    """

    def __init__(self, default_stream):
        self._default = default_stream
        self._local = threading.local()

    def _target(self):
        return getattr(self._local, "buffer", None) or self._default

    def write(self, s):
        return self._target().write(s)

    def flush(self):
        self._target().flush()

    def push(self, buffer):
        self._local.buffer = buffer

    def pop(self):
        self._local.buffer = None


_stdout_proxy: Optional[_ThreadLocalStream] = None
_stderr_proxy: Optional[_ThreadLocalStream] = None
_proxy_install_lock = threading.Lock()


def _ensure_output_proxies_installed():
    global _stdout_proxy, _stderr_proxy
    with _proxy_install_lock:
        if _stdout_proxy is None:
            _stdout_proxy = _ThreadLocalStream(sys.stdout)
            sys.stdout = _stdout_proxy
        if _stderr_proxy is None:
            _stderr_proxy = _ThreadLocalStream(sys.stderr)
            sys.stderr = _stderr_proxy


@contextlib.contextmanager
def _capture_output():
    _ensure_output_proxies_installed()
    buffer = io.StringIO()
    _stdout_proxy.push(buffer)
    _stderr_proxy.push(buffer)
    try:
        yield buffer
    finally:
        _stdout_proxy.pop()
        _stderr_proxy.pop()

_BN_CONSOLE_LOG = Path.home() / ".binaryninja" / "logs" / "mcp_server_bn_console.log"
# The real directory BN's own Snippet plugin reads from (see BN's own docs,
# "User Files" -- snippets/: "Used to store snippets created using the
# official Snippet plugin") -- writing here, not a plugin-private folder,
# is what makes create_snippet's output show up in BN's Snippet Manager.
_SNIPPETS_DIR = Path.home() / ".binaryninja" / "snippets"
_SNIPPET_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")

_jobs_lock = threading.Lock()
_jobs: dict[str, "_ScriptJob"] = {}
_log_redirect_started = False


@dataclass
class _ScriptJob:
    id: str
    status: str = "running"  # running | completed | error | cancelled
    output: Optional[str] = None
    error: Optional[str] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None


def _run_script_body(script: str, cancel_event: threading.Event) -> str:
    namespace = {
        "binaryninja": binaryninja,
        "should_cancel": cancel_event.is_set,
    }
    with _capture_output() as captured:
        exec(compile(script, "<mcp_execute_script>", "exec"), namespace)
    return captured.getvalue()


@serialized
def _execute_sync(script: str) -> dict:
    # The call itself is logged generically by log_tool_call (see
    # concurrency.py) at registration time -- this only logs the *outcome*,
    # which a generic wrapper can't know (error vs completed).
    try:
        output = _run_script_body(script, threading.Event())
    except Exception as exc:
        binaryninja.log_error(f"[mcp-server] execute_script failed: {exc}")
        logger.error(f"execute_script failed: {exc}\n{traceback.format_exc()}")
        raise
    return {"status": "completed", "output": output}


def _execute_async(script: str) -> dict:
    job_id = uuid.uuid4().hex
    job = _ScriptJob(id=job_id)
    with _jobs_lock:
        _jobs[job_id] = job

    def runner():
        try:
            output = _run_script_body(script, job.cancel_event)
            job.status = "cancelled" if job.cancel_event.is_set() else "completed"
            job.output = output
            binaryninja.log_info(f"[mcp-server] execute_script job {job_id} {job.status}")
        except Exception as exc:
            job.status = "error"
            job.error = f"{exc}\n{traceback.format_exc()}"
            binaryninja.log_error(f"[mcp-server] execute_script job {job_id} failed: {exc}")
            logger.error(f"execute_script job {job_id} failed: {exc}")

    job.thread = threading.Thread(target=runner, name=f"mcp-script-{job_id}", daemon=True)
    job.thread.start()
    return {"status": "running", "job_id": job_id}


def execute_script(script: str, async_run: bool = False) -> dict:
    """Execute a Python script inside the running Binary Ninja process.

    By default runs synchronously and blocks other MCP tool calls until it
    finishes (matching the server's normal serialized execution). Pass
    async_run=True for long-running scripts: this returns immediately with
    a job_id, runs the script on its own thread without blocking other tool
    calls, and does not hold the global sync-tool lock. Poll
    get_script_status(job_id) for the result, or cancel_script(job_id) to
    request a best-effort stop (the script must itself check
    should_cancel() -- there is no hard interrupt).

    Every tool call is logged to BN's log console (see register()); this
    additionally logs the outcome (completion/error/cancellation), which a
    generic call-logger can't know.
    """
    if not async_run:
        return _execute_sync(script)
    return _execute_async(script)


def load_script(path: str, async_run: bool = False) -> dict:
    """Load a Python script file and execute it, same semantics as
    execute_script (including the async_run flag)."""
    script = Path(path).expanduser().read_text()
    return execute_script(script, async_run=async_run)


@serialized
def get_script_status(job_id: str) -> dict:
    """Check the status/result of an async execute_script/load_script job."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return {"status": "not_found"}
    return {"status": job.status, "output": job.output, "error": job.error}


@serialized
def cancel_script(job_id: str) -> dict:
    """Request cancellation of a running async script job. Best-effort --
    only takes effect if the script itself calls should_cancel()."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return {"status": "not_found"}
    job.cancel_event.set()
    return {"status": "cancel_requested"}


def _matches(pattern: str, regex: Optional[re.Pattern], text: str) -> bool:
    if not text:
        return False
    if regex:
        return bool(regex.search(text))
    return pattern.lower() in text.lower()


@serialized
def search_docs(pattern: str, limit: int = 30) -> dict:
    """Search Binary Ninja's Python API (binaryninja package) for
    classes/functions whose name or docstring matches `pattern` (substring,
    or a regex if `pattern` compiles as one)."""
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        regex = None

    results = []

    def scan_module(mod) -> bool:
        for member_name, member in inspect.getmembers(mod):
            if member_name.startswith("_"):
                continue
            if not (inspect.isclass(member) or inspect.isfunction(member) or inspect.ismethod(member)):
                continue
            doc = inspect.getdoc(member) or ""
            if _matches(pattern, regex, member_name) or _matches(pattern, regex, doc):
                results.append(
                    {
                        "name": f"{mod.__name__}.{member_name}",
                        "summary": doc.strip().splitlines()[0] if doc.strip() else "",
                    }
                )
                if len(results) >= limit:
                    return True
        return False

    if not scan_module(binaryninja):
        seen = {binaryninja.__name__}
        for _, modname, _ in pkgutil.walk_packages(binaryninja.__path__, prefix="binaryninja."):
            if modname in seen:
                continue
            seen.add(modname)
            try:
                mod = importlib.import_module(modname)
            except Exception:
                continue
            if scan_module(mod):
                break

    return {"results": results}


def _ensure_log_redirect():
    global _log_redirect_started
    if _log_redirect_started:
        return
    _BN_CONSOLE_LOG.parent.mkdir(parents=True, exist_ok=True)
    binaryninja.log_to_file(LogLevel.InfoLog, str(_BN_CONSOLE_LOG), append=True)
    _log_redirect_started = True


@serialized
def read_logs(limit: int = 100, offset: int = 0) -> dict:
    """Read recent Binary Ninja log lines (most recent first), paginated."""
    if not _BN_CONSOLE_LOG.exists():
        return {"lines": [], "total": 0}
    lines = _BN_CONSOLE_LOG.read_text(errors="replace").splitlines()
    lines.reverse()
    return {"lines": lines[offset : offset + limit], "total": len(lines)}


@serialized
def create_snippet(name: str, script: str) -> dict:
    """Save a reusable script snippet by name into BN's own snippets/
    directory, so it shows up in BN's Snippet Manager (not just something
    load_script can read back). Refuses to overwrite an existing snippet --
    pick a different name instead."""
    if not _SNIPPET_NAME_RE.match(name):
        raise ValueError("snippet name must match [a-zA-Z0-9_-]+")
    _SNIPPETS_DIR.mkdir(parents=True, exist_ok=True)
    path = _SNIPPETS_DIR / f"{name}.py"
    if path.exists():
        raise FileExistsError(f"snippet {name!r} already exists at {path}; choose a different name")
    path.write_text(script)
    return {"path": str(path)}


def register(mcp) -> None:
    _ensure_log_redirect()
    # log_tool_call wraps each tool so every call -- not just
    # execute_script/load_script -- gets an INFO line in BN's log console.
    # functools.wraps sets __wrapped__, so FastMCP's schema introspection
    # still sees each tool's real signature through the wrapper.
    for fn, name in (
        (execute_script, "execute_script"),
        (load_script, "load_script"),
        (get_script_status, "get_script_status"),
        (cancel_script, "cancel_script"),
        (search_docs, "search_docs"),
        (read_logs, "read_logs"),
        (create_snippet, "create_snippet"),
    ):
        mcp.add_tool(log_tool_call(fn), name=name, description=fn.__doc__)
