"""mcp-server Phase 1+2 smoke test (server skeleton + scripting tools) --
run via Binary Ninja's Tools > Run Script (or paste into the built-in
Python console), per ADR-0009. No test binary/BinaryView is needed yet:
neither phase has bv-dependent tools.

Checks, in order (each prints PASS/FAIL and keeps going):
  A. Settings are registered with the expected (real, production) defaults.
  B. start_server() actually opens a listening HTTP socket.
  C. A request with no API key is rejected (401) once a key exists.
  D. A request with the correct API key succeeds.
  E. /health is reachable without a key regardless of auth state.
  F. stop_server() actually closes the socket.
  G. ensure_api_key() persists across a second start_server() call.
  H. scripting tools are NOT registered when mcp_server.scripting_enabled=False.
  I. scripting tools ARE registered when mcp_server.scripting_enabled=True.
  J. execute_script() runs synchronously and returns real output.
  K. execute_script(async_run=True) + get_script_status + cancel_script.
  L. Thread-local output capture doesn't swallow other threads' stdout.
  M. search_docs() finds a real API symbol.
  N. read_logs() picks up a log line emitted after registration.
  O. create_snippet() writes into BN's real snippets/ dir, cleaned up after.
  P. create_snippet() refuses to overwrite an existing snippet.

This test necessarily calls into real `mcp_server.api_key` /
`mcp_server.api_key_generated` / `mcp_server.scripting_enabled` BN settings
(ensure_api_key() and the tool registry have no test-mode override) -- it
snapshots and restores all three around the run so it never leaves stray
state in your real settings store. The listen port is overridden via
`start_server(port=...)` instead of the `mcp_server.http_port` setting, so
it never touches that real value either. create_snippet() also writes into
BN's *real* `~/.binaryninja/snippets/` directory (that's the point -- it's
what makes the snippet show up in BN's own Snippet Manager) -- the test
uses a unique, obviously-test-only name and deletes exactly that one file
afterward; it never lists or touches anything else in that directory.
"""

import asyncio
import importlib.util
import io
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve()
_PLUGIN_DIR = _HERE.parent.parent  # ai/mcp-server
_REPO_ROOT = _PLUGIN_DIR.parent.parent

_TEST_PORT = 19090  # arbitrary, unlikely to collide with a real running instance

_PASS, _FAIL = [], []


def _report(status, name, detail=""):
    bucket = {"PASS": _PASS, "FAIL": _FAIL}[status]
    bucket.append(name)
    line = f"[{status}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)


def _load_plugin_modules():
    """Import api.py/server.py as real package submodules (so their `.core`
    relative imports resolve) without executing __init__.py -- that would
    register PluginCommands/Settings a second time if the plugin is also
    installed normally."""
    pkg_name = "_mcp_server_test_harness"
    if f"{pkg_name}.api" in sys.modules:
        return sys.modules[f"{pkg_name}.api"]

    pkg_spec = importlib.util.spec_from_file_location(
        pkg_name,
        _PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(_PLUGIN_DIR), str(_REPO_ROOT)],
    )
    pkg = importlib.util.module_from_spec(pkg_spec)
    sys.modules[pkg_name] = pkg  # shell only -- deliberately not exec'd

    for name in ("concurrency", "server", "scripting", "api"):
        spec = importlib.util.spec_from_file_location(f"{pkg_name}.{name}", _PLUGIN_DIR / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = pkg_name
        sys.modules[f"{pkg_name}.{name}"] = mod
        spec.loader.exec_module(mod)

    return sys.modules[f"{pkg_name}.api"]


def _list_tool_names(mcp):
    return [t.name for t in asyncio.run(mcp.list_tools())]


def _register_settings():
    """Register the plugin's real settings with their real (production)
    defaults -- a no-op if the plugin's __init__.py already did this via a
    normal install."""
    from binaryninja import Settings

    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from core.settings import register_setting

    register_setting("mcp_server.bind_address", "test", "127.0.0.1")
    register_setting("mcp_server.http_port", "test", 9090)
    register_setting("mcp_server.api_key", "test", "")
    register_setting("mcp_server.api_key_generated", "test", False)
    register_setting("mcp_server.scripting_enabled", "test", False)
    return Settings()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def _run_checks(api, settings):
    # -- A. settings registered with expected (real) defaults ------------
    try:
        assert settings.get_string("mcp_server.bind_address") == "127.0.0.1"
        assert settings.contains("mcp_server.http_port")
        assert settings.contains("mcp_server.api_key_generated")
        _report("PASS", "A. settings registered with expected defaults")
    except AssertionError as e:
        _report("FAIL", "A. settings registered with expected defaults", str(e))

    base_url = f"http://127.0.0.1:{_TEST_PORT}"

    # -- B. start_server() opens a listening socket ----------------------
    try:
        server = api.start_server(port=_TEST_PORT)
        assert server.running
        status = api.get_server_status()
        assert status.running and status.port == _TEST_PORT
        _report("PASS", "B. start_server() opens a listening socket")
    except Exception as e:
        _report("FAIL", "B. start_server() opens a listening socket", str(e))
        return  # nothing else can run without a live server

    key = api.ensure_api_key()

    # -- B2. consolidated `list` tool replaces the old per-kind get_* tools -
    try:
        names = set(_list_tool_names(server.mcp))
        removed = {"get_functions", "get_symbols", "get_types", "get_sections", "get_imports", "get_exports", "get_strings"}
        expected = {"list", "get_function", "get_xrefs_to", "get_xrefs_from", "get_type", "get_data", "search"}
        assert "list" in names, "consolidated `list` tool not registered"
        assert not (names & removed), f"old per-kind tools still registered: {names & removed}"
        assert expected.issubset(names), f"missing: {expected - names}"
        _report("PASS", "B2. `list` tool present, old per-kind get_* tools gone")
    except Exception as e:
        _report("FAIL", "B2. `list` tool present, old per-kind get_* tools gone", str(e))

    # -- C. request without a key is rejected -----------------------------
    try:
        code = _get(f"{base_url}/mcp")
        assert code == 401, f"expected 401, got {code}"
        _report("PASS", "C. request without API key rejected (401)")
    except Exception as e:
        _report("FAIL", "C. request without API key rejected (401)", str(e))

    # -- D. request with the correct key is accepted ----------------------
    try:
        code = _get(f"{base_url}/mcp", headers={"Authorization": f"Bearer {key}"})
        assert code != 401, "got 401 with a correct key"
        _report("PASS", "D. request with correct API key accepted")
    except Exception as e:
        _report("FAIL", "D. request with correct API key accepted", str(e))

    # -- E. /health needs no key -------------------------------------------
    try:
        code = _get(f"{base_url}/health")
        assert code == 200, f"expected 200, got {code}"
        _report("PASS", "E. /health reachable without a key")
    except Exception as e:
        _report("FAIL", "E. /health reachable without a key", str(e))

    # -- F. stop_server() closes the socket --------------------------------
    try:
        api.stop_server()
        assert not server.running
        try:
            _get(f"{base_url}/health")
            raise AssertionError("socket still accepting connections after stop_server()")
        except urllib.error.URLError:
            pass  # connection refused, as expected
        _report("PASS", "F. stop_server() closes the socket")
    except Exception as e:
        _report("FAIL", "F. stop_server() closes the socket", str(e))

    # -- G. ensure_api_key() persists across restart -----------------------
    try:
        api.start_server(port=_TEST_PORT)
        key2 = api.ensure_api_key()
        assert key2 == key, "API key changed across restart"
        api.stop_server()
        _report("PASS", "G. ensure_api_key() persists across restart")
    except Exception as e:
        _report("FAIL", "G. ensure_api_key() persists across restart", str(e))

    scripting = sys.modules["_mcp_server_test_harness.scripting"]
    settings.set_bool("mcp_server.scripting_enabled", False)

    # -- H. scripting tools not registered when disabled --------------------
    try:
        server = api.start_server(port=_TEST_PORT)
        assert "execute_script" not in _list_tool_names(server.mcp)
        api.stop_server()
        _report("PASS", "H. scripting tools absent when scripting_enabled=False")
    except Exception as e:
        _report("FAIL", "H. scripting tools absent when scripting_enabled=False", str(e))

    settings.set_bool("mcp_server.scripting_enabled", True)

    # -- I. scripting tools registered when enabled --------------------------
    try:
        server = api.start_server(port=_TEST_PORT)
        names = _list_tool_names(server.mcp)
        expected = {
            "execute_script",
            "load_script",
            "get_script_status",
            "cancel_script",
            "search_docs",
            "read_logs",
            "create_snippet",
        }
        assert expected.issubset(names), f"missing: {expected - set(names)}"
        _report("PASS", "I. scripting tools present when scripting_enabled=True")
    except Exception as e:
        _report("FAIL", "I. scripting tools present when scripting_enabled=True", str(e))
    finally:
        api.stop_server()

    # -- J. execute_script() runs synchronously -----------------------------
    try:
        result = scripting.execute_script("print(1 + 1)")
        assert result["status"] == "completed"
        assert result["output"].strip() == "2"
        _report("PASS", "J. execute_script() sync runs and returns output")
    except Exception as e:
        _report("FAIL", "J. execute_script() sync runs and returns output", str(e))

    # -- K. async execute_script + status + cancel ---------------------------
    job_id = None
    try:
        kickoff = scripting.execute_script(
            "import time\n"
            "for _ in range(40):\n"
            "    if should_cancel():\n"
            "        break\n"
            "    time.sleep(0.05)\n"
            "print('finished')\n",
            async_run=True,
        )
        assert kickoff["status"] == "running"
        job_id = kickoff["job_id"]
        time.sleep(0.1)
        running_status = scripting.get_script_status(job_id)
        assert running_status["status"] == "running"
        scripting.cancel_script(job_id)
        time.sleep(0.3)
        final_status = scripting.get_script_status(job_id)
        assert final_status["status"] == "cancelled"
        _report("PASS", "K. async execute_script + status + cancel")
    except Exception as e:
        _report("FAIL", "K. async execute_script + status + cancel", str(e))

    # -- L. thread-local capture doesn't swallow other threads' stdout ------
    try:
        captured_main = io.StringIO()
        marker = "MAIN-THREAD-MARKER"

        kickoff = scripting.execute_script(
            "import time\ntime.sleep(0.2)\nprint('job-thread-output')\n", async_run=True
        )
        import sys as _sys

        real_stdout = _sys.stdout
        _sys.stdout = captured_main
        try:
            print(marker)
        finally:
            _sys.stdout = real_stdout
        time.sleep(0.4)
        assert marker in captured_main.getvalue(), "main thread's own print() was swallowed"
        job_result = scripting.get_script_status(kickoff["job_id"])
        assert "job-thread-output" in (job_result["output"] or "")
        _report("PASS", "L. thread-local output capture is isolated per-thread")
    except Exception as e:
        _report("FAIL", "L. thread-local output capture is isolated per-thread", str(e))

    # -- M. search_docs() finds a real API symbol ----------------------------
    try:
        docs = scripting.search_docs("BinaryView", limit=5)
        assert docs["results"], "expected at least one match for 'BinaryView'"
        _report("PASS", "M. search_docs() finds a real API symbol")
    except Exception as e:
        _report("FAIL", "M. search_docs() finds a real API symbol", str(e))

    # -- N. read_logs() picks up a log line emitted after registration -------
    try:
        import binaryninja

        marker = f"mcp-server test log {time.time()}"
        binaryninja.log_info(marker)
        logs = scripting.read_logs(limit=10)
        assert any(marker in line for line in logs["lines"]), "log line not found in read_logs()"
        _report("PASS", "N. read_logs() picks up a log line emitted after registration")
    except Exception as e:
        _report("FAIL", "N. read_logs() picks up a log line emitted after registration", str(e))

    # -- O. create_snippet() writes into BN's real snippets/ dir ------------
    snippet_name = f"mcp_server_test_snippet_{uuid.uuid4().hex[:8]}"
    path = None
    try:
        snippet = scripting.create_snippet(snippet_name, "print('hi')")
        path = Path(snippet["path"])
        assert path.parent.name == "snippets" and path.parent.parent == Path.home() / ".binaryninja"
        assert path.is_file()
        assert path.read_text() == "print('hi')"
        _report("PASS", "O. create_snippet() writes into BN's real snippets/ dir")
    except Exception as e:
        _report("FAIL", "O. create_snippet() writes into BN's real snippets/ dir", str(e))

    # -- P. create_snippet() refuses to overwrite ----------------------------
    try:
        assert path is not None and path.is_file(), "setup from O did not produce a file"
        try:
            scripting.create_snippet(snippet_name, "print('overwritten')")
            raise AssertionError("create_snippet() overwrote an existing snippet")
        except FileExistsError:
            pass
        assert path.read_text() == "print('hi')", "snippet content changed despite refusing overwrite"
        _report("PASS", "P. create_snippet() refuses to overwrite an existing snippet")
    except Exception as e:
        _report("FAIL", "P. create_snippet() refuses to overwrite an existing snippet", str(e))
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def main():
    api = _load_plugin_modules()
    settings = _register_settings()

    # Snapshot the settings this test mutates, so the run doesn't permanently
    # alter your real MCP server auth/scripting state.
    orig_api_key = settings.get_string("mcp_server.api_key")
    orig_api_key_generated = settings.get_bool("mcp_server.api_key_generated")
    orig_scripting_enabled = settings.get_bool("mcp_server.scripting_enabled")
    try:
        _run_checks(api, settings)
    finally:
        api.stop_server()
        settings.set_string("mcp_server.api_key", orig_api_key)
        settings.set_bool("mcp_server.api_key_generated", orig_api_key_generated)
        settings.set_bool("mcp_server.scripting_enabled", orig_scripting_enabled)

    print(f"\n{len(_PASS)} passed, {len(_FAIL)} failed")


if __name__ == "__main__":
    main()
