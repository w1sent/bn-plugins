# MCP Server

Exposes Binary Ninja's database as an MCP (Model Context Protocol) server, so
external AI tools (Claude Code, Codex, OpenCode, DeepAgents, ...) can read,
write, script, and debug through a real, running BN session over HTTP.

## Architecture

- Runs inside BN as a background thread; starts on load (`mcp_server.enabled`,
  default on), stops on unload.
- Transport: HTTP only. Stdio is deferred -- BN is a long-running GUI process
  that owns the server lifecycle, which doesn't fit stdio's "client spawns the
  process" model; a stdio-to-HTTP proxy shim could bridge this later.
- Binds to `127.0.0.1` by default (`mcp_server.bind_address`); auth via an
  auto-generated API key (`mcp_server.api_key`), which can be disabled
  entirely by clearing it.
- Tool-call execution is serialized server-wide (a single global lock) --
  async script jobs (`execute_script(async_run=True)`) are the deliberate
  exception, so a long-running script doesn't block other tool calls.
- Tool categories disabled via settings are excluded from the MCP tool list
  entirely (not registered), not merely blocked at call time -- a client
  never sees a tool it isn't allowed to use. Toggling a setting takes effect
  on the next server restart, not live.
- Which binary tools operate on is resolved via `binary_context.py`: an
  explicit `select_binary`/`load_binary` selection if one is set (and still
  open), otherwise whichever binary is focused in the GUI's current tab.
- All `binaryninjaui`/Qt access is marshalled onto BN's main thread via
  `binaryninja.execute_on_main_thread_and_wait` -- calling it directly from
  the MCP server's own thread crashes BN (Qt isn't thread-safe).

## Tools

### Read (always registered)

Per [ADR-0038](../../docs/adr/0038-binja-cli-skill-frontend.md), the old
one-tool-per-kind listing tools (`get_functions`, `get_symbols`,
`get_types`, `get_sections`, `get_imports`, `get_exports`, `get_strings`)
are gone, replaced by one consolidated `list`. All read/list tools return
plain text (a header line + tab-separated records), never JSON -- see that
ADR's "Output format" section.

| Tool | Description |
|---|---|
| `get_function(name_or_addr, il_level)` | Function metadata + disassembly/LLIL/MLIL/HLIL/LLIL_SSA/MLIL_SSA/HLIL_SSA |
| `list(kind, name_regex, fields, limit, offset)` | Filtered, paginated listing; `kind` is one of `functions`/`symbols`/`types`/`sections`/`imports`/`exports`/`strings` |
| `get_xrefs_to(addr, limit, offset)` | Cross-references to an address |
| `get_xrefs_from(addr, limit, offset)` | Cross-references from an address |
| `get_type(name)` | A specific type's definition |
| `get_data(addr, size)` | Raw bytes at an address (hex) |
| `search(pattern)` | Search function/symbol names and strings (substring or regex) across all three kinds at once; for one kind specifically, prefer `list(kind, name_regex=pattern)` |

### Write -- safe (`mcp_server.write_enabled`, default **on**)

Low-risk, easily reversible; only ever add/replace user-attributed metadata
(names, comments, types, function boundaries), never binary bytes.

| Tool | Description |
|---|---|
| `rename_function(addr, name)` | Rename a function |
| `rename_symbol(addr, name)` | Rename a symbol |
| `set_comment(addr, comment)` | Set a comment at an address |
| `set_function_comment(addr, comment)` | Set a function-level comment |
| `create_struct(c_struct)` | Define a struct type from C struct syntax |
| `load_header(path)` | Define all types declared in a C header file |
| `set_type(addr, type_name)` | Apply a type to an address (defines a data variable) |
| `create_function(addr)` | Create a function at an address |

### Undo (`mcp_server.undo_enabled`, default **off**)

Separate from the safe-write tier because it reverts BN's undo stack
wholesale, including manual edits the human made in the GUI, not just
AI/tool-made changes. Off by default so an agent can't silently discard the
user's own work.

| Tool | Description |
|---|---|
| `undo_action(steps=1)` | Revert the last `steps` change(s) via BN's native undo mechanism |

### Write -- destructive (`mcp_server.destructive_write_enabled`, default **off**)

Can corrupt the file/analysis, unlike the safe-write tier.

| Tool | Description |
|---|---|
| `patch_asm(addr, assembly)` | Assemble for the binary's architecture and write the result at `addr` |
| `edit_hex(addr, hex)` | Overwrite bytes at `addr` with raw hex |

See "Future improvements" for `patch_c`.

### Scripting (`mcp_server.scripting_enabled`, default **off**)

`execute_script`/`load_script` are arbitrary code execution inside the BN
process -- the point is using the MCP server itself as a stand-in for BN's
commercial-only headless mode when testing plugins.

| Tool | Description |
|---|---|
| `execute_script(script, async_run=False)` | Execute a script; `async_run=True` runs it on its own thread without blocking other tool calls |
| `load_script(path, async_run=False)` | Load and execute a Python script file, same semantics as `execute_script` |
| `get_script_status(job_id)` | Check status/result of an async script job |
| `cancel_script(job_id)` | Request cancellation of a running async script job (best-effort) |
| `search_docs(pattern, limit=30)` | Search Binary Ninja's Python API for matching classes/functions |
| `read_logs(limit=100, offset=0)` | Read recent BN log lines, most recent first |
| `create_snippet(name, script)` | Save a script into BN's real `snippets/` directory (visible in the Snippet Manager); refuses to overwrite an existing snippet |
| `list_snippets()` | List snippets available in BN's `snippets/` directory, by name |
| `run_snippet(name, async_run=False)` | Run a snippet by name (see `list_snippets`), same semantics as `execute_script` |

### Administration (always registered)

| Tool | Description |
|---|---|
| `select_binary(index)` | Select which open binary subsequent tool calls operate on, by index into `program://binaries` |
| `load_binary(path)` | Open a binary/`.bndb` as a new GUI tab and select it |

### Debugging (`mcp_server.debugging_enabled`, default **off**)

Built on `binaryninja.debugger.DebuggerController`. **PIE binaries get
rebased to their live load address once a debug session starts** -- always
re-fetch addresses (e.g. via `get_function`) *after* `launch()`, not before,
when setting breakpoints. Using a pre-launch address causes the process to
run to completion, silently missing the breakpoint.

| Tool | Description |
|---|---|
| `launch()` | Launch the current binary under the debugger; stops at the entry point |
| `set_breakpoint(addr)` | Set a breakpoint |
| `resume()` | Resume execution |
| `run_until(addr)` | Run until a specific address (one-shot breakpoint) |
| `step_into()` | Single-step, stepping into calls |
| `step_over()` | Single-step, stepping over calls |
| `step_return()` | Run until the current function returns |
| `kill_process()` | Stop the debugged process |
| `restart()` | Restart the debugged process |

### GUI utility (`mcp_server.screenshot_enabled`, default **off**)

| Tool | Description |
|---|---|
| `capture_screenshot()` | Capture the whole BN window, returned as inline MCP image content |

## Resources

| Resource | Description |
|---|---|
| `binary://metadata` | Name, arch, platform, entry point, size |
| `binary://functions` | Full function list |
| `binary://symbols` | Full symbol table |
| `binary://types` | All type definitions |
| `binary://sections` | Section list |
| `binary://selected` | The currently selected/focused binary (path, arch, whether the selection is explicit) |
| `program://binaries` | All binaries currently open in the GUI, with their index and selection state |
| `program://plugins` | Installed Binary Ninja plugins (from BN's own plugin manager) |

See "Future improvements" for `gui://status`.

## Prompts

Always registered -- plain message templates for an AI client to send
itself, no side effects.

| Prompt | Description |
|---|---|
| `analyze-function(addr)` | Analyze the function at `addr` and explain what it does |
| `find-crypto` | Find cryptographic routines in this binary |
| `suggest-names` | Suggest meaningful names for unnamed functions |
| `reverse-engineering` | Help reverse engineer this binary |

## Settings (BN native)

| Setting | Type | Default | Description |
|---|---|---|---|
| `mcp_server.enabled` | bool | `true` | Start server on BN load; in GUI this also controls autostart |
| `mcp_server.bind_address` | string | `"127.0.0.1"` | Address the MCP HTTP server binds to |
| `mcp_server.http_port` | int | `9090` | Port for the MCP HTTP server |
| `mcp_server.api_key` | string | auto-generated | API key required to call the server; clear to disable auth |
| `mcp_server.write_enabled` | bool | `true` | Safe write tools |
| `mcp_server.destructive_write_enabled` | bool | `false` | Destructive write tools (`patch_asm`, `edit_hex`) |
| `mcp_server.undo_enabled` | bool | `false` | `undo_action` |
| `mcp_server.scripting_enabled` | bool | `false` | Scripting tools |
| `mcp_server.debugging_enabled` | bool | `false` | Debugger control tools |
| `mcp_server.screenshot_enabled` | bool | `false` | `capture_screenshot` |
| `mcp_server.debug_logging` | bool | `false` | Reserved for future verbose per-call request/response logging; not yet wired up (see "Future improvements"). A basic INFO-level "tool called: name(args)" line for every call is *always* logged to BN's own log console regardless of this setting |
| `mcp_server.echo_target_enabled` | bool | `true` | Prepend a `#binary  index  path` line to read/list output identifying which binary the call ran against; the `bn` CLI reroutes this line to stderr so piped stdout stays clean (see ADR-0038) |

## Menu commands

Under Plugins → MCP Server (GUI only, always available even with no binary
open):

| Command | Description |
|---|---|
| Start Server | Start the MCP server |
| Stop Server | Stop the MCP server |
| Copy API Key | Copy the current API key to the clipboard |

## Status bar indicator

A small `MCP :<port>` label appears in Binary Ninja's main window status bar
while the server is running (hover for host/port), and disappears entirely
when it's stopped. Not gated by any setting -- it just mirrors server state.

## API (`api.py`)

```python
start_server(*, host=None, port=None) -> MCPServer
stop_server(server=None)
get_server_status() -> ServerStatus
ensure_api_key() -> str
```

Call `api.help()` in BN's Python console for the full docstring.

## Connecting a client

`scripts/install_mcp_clients.py` configures Claude Code, Codex, OpenCode, and
DeepAgents to talk to a running instance of this server -- see that script's
`--help` for usage. It appends to each tool's existing config rather than
overwriting it. For Claude Code, it also installs `skills/binja-mcp/SKILL.md`
into `~/.claude/skills/binja-mcp` -- a skill covering which tool to reach for
in common reversing scenarios (getting oriented, hunting crypto, patching,
scripting, debugging PIE binaries, ...). MCP itself has no skill-registration
primitive (only tools/resources/prompts), so this is a plain file copy, not
something registered over the protocol; pass `--no-skill` to skip it.

To configure a client manually: the server listens at
`http://<bind_address>:<http_port>/mcp` (defaults to
`http://127.0.0.1:9090/mcp`); get the current API key via Plugins → MCP
Server → Copy API Key, and send it as `Authorization: Bearer <key>`.

## CLI front end (`bn`)

`skills/binja-cli/scripts/bn` is a stdlib-only Python script that talks to
this same MCP server as a plain client -- see
[ADR-0038](../../docs/adr/0038-binja-cli-skill-frontend.md) for the full
design. It exists for agent harnesses (like `pi`, https://pi.dev) that
favor a bash-plus-on-demand-skill model over embedding an MCP client, but
works from any shell. It finds a running server with no configuration via a
local connection file this plugin writes on server start/removes on stop
(`~/.cache/binja-mcp/server.json`, 0600) -- see `connection_file.py`; an
explicit `--server`/`--api-key` (or `BN_MCP_URL`/`BN_MCP_API_KEY`) points it
at a non-default one instead. Run `bn --help` / `bn health` for its own
documentation and live status; see the `binja-cli` skill for a usage guide.
Currently covers read/list only -- write/patch/debug/script tools aren't
wrapped yet (see that ADR's Considered/rejected and the skill's "What's not
here" section).

## Dependencies

- `mcp` (vendored per-plugin on install), pinned to `<2.0` (see
  [ADR-0032](../../docs/adr/0032-pin-third-party-plugin-dependencies.md))
- No other deps beyond the BN API + `core/` + `mcp`

## Open migration: `mcp` 2.0

Upstream's `mcp` Python SDK released a stable 2.0.0 on 2026-07-28, alongside a
new MCP spec version that moves the protocol from stateful/bidirectional to
stateless request/response. It renames `mcp.server.fastmcp.FastMCP` to
`mcp.server.mcpserver.MCPServer` (module `mcp.server.fastmcp` is gone) and
moves `Image` to `mcp.server.mcpserver`; `server.py` and `gui.py` import both
directly. The high-level `@mcp.tool` / `@mcp.resource` / `@mcp.prompt`
decorator API used throughout `administration.py`, `reading.py`, and
`prompts.py` appears unchanged in shape, so the migration is expected to be
mostly a rename plus verifying the new stateless request/response behavior
against this plugin's tool-call serialization (see Architecture). Pinned to
`mcp<2.0` for now (see [ADR-0033](../../docs/adr/0033-cutting-edge-check-upstream-versions-on-change.md))
since the release is brand new and not yet battle-tested; revisit once it has
had time to stabilize.

## Future improvements

- **`patch_c(addr, c_code)`** -- patch the binary at a location using a C
  code snippet. Deferred: Binary Ninja's Python API has no headless
  C-compile facility. The GUI's `binaryninjaui.CompileDialog` looked
  promising, but its compile step is wired to an internal button's Qt
  signal, not a public method -- confirmed live that calling `.accept()`
  directly just closes the dialog without compiling (`getBytes()` comes back
  empty). Revisit if a public, non-interactive compile entry point appears
  in a future BN version.
- **`gui://status`** resource -- current user-interaction state (opened
  function, opened view, focused panel). Not yet implemented.
- **Stdio transport** -- deferred in favor of HTTP-only for v1; would need a
  stdio-to-HTTP proxy shim given BN's process lifecycle (see Architecture).
- **`mcp_server.debug_logging`** -- the setting is registered but not yet
  consumed anywhere; intended for opt-in verbose per-call request/response
  logging beyond the always-on basic call log.
