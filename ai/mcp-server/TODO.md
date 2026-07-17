# mcp-server — MCP server for Binary Ninja

## Scope
- [ ] Expose Binary Ninja's database as an MCP (Model Context Protocol) server
- [ ] Allow external AI tools (Claude Desktop, Cursor, Continue, etc.) to interact with BN
- [ ] Tools for reading: functions, disassembly, symbols, types, cross-references, data
- [ ] Tools for writing: rename, create types, set comments, create structs
- [ ] Resources: current binary metadata, function list, symbol table, GUI/user-activity state
- [ ] Prompts: pre-built prompt templates for common RE tasks

## Architecture
- [ ] MCP server runs inside BN as a background thread
- [ ] BN plugin starts the server on load, stops on unload; for GUI, autostart is configurable via `mcp_server.enabled` (default `true`)
- [ ] Transport: HTTP only for v1. Stdio is deferred — BN is a long-running GUI process that owns the server lifecycle, which doesn't fit stdio's "client spawns the process" model; revisit later, possibly via a stdio-to-HTTP proxy shim
- [ ] Bind address defaults to `127.0.0.1` (localhost only); overridable for remote/headless use via `mcp_server.bind_address`
- [ ] Auth: API key is auto-generated on first server start and used by default. Auth can be turned off entirely by clearing the key (not required — just the sane default)
- [ ] Tool-call execution is serialized server-wide (single global lock) for v1 — no concurrent tool execution yet; revisit if usage patterns demand it
- [ ] Tool categories disabled via settings are excluded from the MCP tool list entirely (not registered), not merely blocked at call time — an AI client should never see a tool it can't use

## Implementation phases
Build in this order; each phase should be independently usable.
1. **Server skeleton** — lifecycle (start/stop on load/unload, GUI autostart setting), core settings, `get_server_status()`, empty tool registry, auto-generated API key + "Copy MCP API Key" menu command
2. **Scripting tools** — enables using the MCP server itself as a headless-mode substitute for testing BN/plugins (commercial-only headless isn't available); highest priority after the skeleton for that reason
3. **Read tools + resources** — the core read-only RE-assistant use case
4. **Safe write tools** — rename/comment/type/struct/function creation, on by default
5. **Prompts**
6. **Administration** — multi-binary selection
7. **Destructive write tools** — binary patching, off by default
8. **Debugging tools** — off by default, lowest priority (effectively a second plugin's surface)

## MCP Tools (read)
Always registered -- no gating setting (the core read-only use case). Operate on `binary_context.get_current_view()` (whichever binary is focused in the GUI; explicit `select_binary` comes in the administration phase).
- [x] `get_function(name_or_addr, il_level)` — function metadata + disassembly/LLIL/MLIL/HLIL/LLIL_SSA/MLIL_SSA/HLIL_SSA
- [x] `get_functions(limit, offset)` — paginated function list
- [x] `get_symbols(limit, offset)` — all symbols with names, addresses, types
- [x] `get_xrefs_to(addr)` — cross-references to an address
- [x] `get_xrefs_from(addr)` — cross-references from an address
- [x] `get_types()` — all user-defined types
- [x] `get_type(name)` — specific type definition
- [x] `get_data(addr, size)` — raw bytes at address
- [x] `get_strings(limit, offset)` — paginated string list
- [x] `get_sections()` — binary sections with permissions (inferred from containing segment)
- [x] `get_imports()` — imported functions/data
- [x] `get_exports()` — exported (globally-bound) functions/data
- [x] `search(pattern)` — search function/symbol names and defined strings for a substring or regex

## MCP Tools (write — safe)
Gated by `mcp_server.write_enabled` (default **on**) — low-risk, easily reversible operations; only ever add/replace user-attributed metadata (names, comments, types, function boundaries), never binary bytes.
- [x] `rename_function(addr, name)` — rename a function
- [x] `rename_symbol(addr, name)` — rename a symbol
- [x] `set_comment(addr, comment)` — set a comment at address
- [x] `set_function_comment(addr, comment)` — set function-level comment
- [x] `create_struct(c_struct)` — create a struct type from C struct syntax
- [x] `load_header(path)` — create all types in a header file
- [x] `set_type(addr, type_name)` — apply a type to an address (defines a data variable)
- [x] `create_function(addr)` — create a function at address

## MCP Tools (undo)
Gated by its own setting `mcp_server.undo_enabled` (default **off**) — separate from safe-writes because it reverts BN's undo stack wholesale, including manual edits the human made in the GUI, not just AI/tool-made changes. Off by default so an agent can't silently discard the user's own work.
- [ ] `undo_action(steps=1)` — reverts the last `steps` changes via BN's native undo mechanism (affects user changes too, not just tool-made ones)

## MCP Tools (write — destructive)
Gated by `mcp_server.destructive_write_enabled` (default **off**) — can corrupt the file/analysis, unlike the safe-write tier.
- [ ] `patch_asm(addr, assembly)` — patch the binary at a location using assembly
- [ ] `patch_c(addr, c_code)` — patch the binary at a location using a C code snippet
- [ ] `edit_hex(addr, hex)` — edit the file at the given location using raw hex

## MCP Tools (scripting)
Gated by `mcp_server.scripting_enabled` (default **off**) — `execute_script`/`load_script` are arbitrary code execution inside the BN process. `execute_script` and `load_script` support an optional async flag (default sync execution); async jobs are pollable and cancellable.
- [ ] `execute_script(script, async=False)` — execute a passed script
- [ ] `load_script(path, async=False)` — load a python script into BN
- [ ] `get_script_status(job_id)` — check status/result of an async script job
- [ ] `cancel_script(job_id)` — cancel a running async script job
- [ ] `search_docs(search_pattern)` — searches BN API docs and returns results
- [ ] `read_logs(limit, offset)` — read the BN log
- [ ] `create_snippet(name, script)` — save a snippet into BN's own `snippets/` directory (visible in BN's Snippet Manager); refuses to overwrite an existing snippet

## MCP Tools (administration)
Always registered -- no gating setting.
- [x] `select_binary(id)` — switch which binary is affected by the MCP tools; `id` is the integer index into `program://binaries`
- [x] `load_binary(path)` — load a binary or bndb (opens it as a new GUI tab and selects it)

## MCP Tools (debugging)
Gated by `mcp_server.debugging_enabled` (default **off**).
- [ ] `launch()` — launch debugger
- [ ] `set_breakpoint(addr)` — set breakpoint
- [ ] `resume()` — resume execution
- [ ] `run_until(addr)` — execute till an address
- [ ] `step_into()` — step into function
- [ ] `step_over()` — step over
- [ ] `step_return()` — run till function returns
- [ ] `kill_process()` — stop debugged process
- [ ] `restart()` — restarts debugged process

## MCP Tools (GUI utility)
Gated by `mcp_server.screenshot_enabled` (default **off**).
- [ ] `capture_screenshot()` — captures the whole BN window, returned inline as MCP image content (useful when discussing something visually with the user)

## MCP Resources
- [x] `binary://metadata` — binary name, arch, platform, entry point, size
- [x] `binary://functions` — full function list
- [x] `binary://symbols` — full symbol table
- [x] `binary://types` — all type definitions
- [x] `binary://sections` — section list
- [x] `binary://selected` — the currently selected binary (per `select_binary`)
- [x] `program://plugins` — lists installed plugins
- [x] `program://binaries` — lists loaded binaries
- [ ] `gui://status` — current user-interaction state: opened function, opened view, focused panel

## MCP Prompts
Always registered -- templates for an AI client to send itself, no side effects, no gating setting.
- [x] `analyze-function` — "Analyze the function at {addr} and explain what it does"
- [x] `find-crypto` — "Find cryptographic routines in this binary"
- [x] `suggest-names` — "Suggest meaningful names for unnamed functions"
- [x] `reverse-engineering` — "Help me reverse engineer this binary"

## Settings (BN native)
- [ ] `mcp_server.enabled` (bool, default `true`) — start server on BN load; in GUI this also controls autostart
- [ ] `mcp_server.transport` (enum: `"http"` only for v1; `"stdio"` reserved for a future phase)
- [ ] `mcp_server.bind_address` (string, default `"127.0.0.1"`) — set to `"0.0.0.0"` or a specific interface for remote/headless use
- [ ] `mcp_server.http_port` (int, default `9090`) — port for HTTP transport
- [ ] `mcp_server.api_key` (string, auto-generated on first start) — clear to disable auth entirely
- [ ] `mcp_server.write_enabled` (bool, default `true`) — safe write tools (rename, comment, type, struct, function creation)
- [ ] `mcp_server.destructive_write_enabled` (bool, default `false`) — binary patching tools (`patch_asm`, `patch_c`, `edit_hex`)
- [ ] `mcp_server.undo_enabled` (bool, default `false`) — `undo_action`; reverts BN's undo stack including manual user edits, not just tool-made changes
- [ ] `mcp_server.scripting_enabled` (bool, default `false`) — `execute_script`/`load_script`/etc.
- [ ] `mcp_server.debugging_enabled` (bool, default `false`) — debugger control tools
- [ ] `mcp_server.screenshot_enabled` (bool, default `false`) — `capture_screenshot`
- [ ] `mcp_server.debug_logging` (bool, default `false`) — logs full MCP tool-call requests/responses (verbose) to the per-plugin file, mirroring the existing LLM debug-logging pattern. Note: a basic INFO-level "tool called: name(args)" line for every call is *always* logged to BN's own log console regardless of this setting (see `concurrency.log_tool_call`) -- this setting is for deeper, opt-in detail beyond that

## Menu commands
- [ ] "Copy MCP API Key" — copies the current API key to the clipboard (instead of only writing it to the log)

## API (`api.py`)
- [ ] `start_server(bv, *, port=None) -> MCPServer`
- [ ] `stop_server(server)`
- [ ] `get_server_status() -> ServerStatus`
- [ ] `api.help()`
- [ ] All functions fully type-hinted

## Dependencies
- [ ] `mcp` pip package (vendored per-plugin)
- [ ] No other deps beyond BN API + core + mcp

## Notes
- MCP spec: https://modelcontextprotocol.io
- Python SDK: `pip install mcp`
- HTTP transport: MCP client connects to BN's HTTP endpoint; stdio deferred (see Architecture)
- Write tools are split by risk tier (safe / destructive / undo) so users can enable only what they're comfortable with, rather than one all-or-nothing toggle
- Consider: tool descriptions should be detailed so the AI client knows how to use them
- Add skill that describes how to best use the mcp-server, basic concepts of BN and basic strategy of reverse engineering. This skill should be noted in the mcp description.
