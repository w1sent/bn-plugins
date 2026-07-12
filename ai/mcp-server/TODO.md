# mcp-server — MCP server for Binary Ninja

## Scope
- [ ] Expose Binary Ninja's database as an MCP (Model Context Protocol) server
- [ ] Allow external AI tools (Claude Desktop, Cursor, Continue, etc.) to interact with BN
- [ ] Tools for reading: functions, disassembly, symbols, types, cross-references, data
- [ ] Tools for writing: rename, create types, set comments, create structs
- [ ] Resources: current binary metadata, function list, symbol table
- [ ] Prompts: pre-built prompt templates for common RE tasks

## Architecture
- [ ] MCP server runs inside BN as a background thread (stdio or HTTP transport)
- [ ] BN plugin starts the server on load, stops on unload
- [ ] Configurable transport: stdio (default, for local tools) or HTTP/SSE (for remote)
- [ ] Auth: optional API key for HTTP transport

## MCP Tools (read)
- [ ] `get_function(name_or_addr)` — function metadata + disassembly
- [ ] `get_functions(limit, offset)` — paginated function list
- [ ] `get_symbols()` — all symbols with names, addresses, types
- [ ] `get_xrefs_to(addr)` — cross-references to an address
- [ ] `get_xrefs_from(addr)` — cross-references from an address
- [ ] `get_types()` — all user-defined types
- [ ] `get_type(name)` — specific type definition
- [ ] `get_data(addr, size)` — raw bytes at address
- [ ] `get_strings(limit, offset)` — paginated string list
- [ ] `get_sections()` — binary sections with permissions
- [ ] `get_imports()` — imported functions
- [ ] `get_exports()` — exported functions
- [ ] `search(pattern)` — search for pattern in binary
- [ ] `decompile(addr)` — HLIL decompilation of function

## MCP Tools (write)
- [ ] `rename_function(addr, name)` — rename a function
- [ ] `rename_symbol(addr, name)` — rename a symbol
- [ ] `set_comment(addr, comment)` — set a comment at address
- [ ] `set_function_comment(addr, comment)` — set function-level comment
- [ ] `create_struct(name, fields)` — create a struct type
- [ ] `set_type(addr, type_name)` — apply a type to an address
- [ ] `create_function(addr)` — create a function at address

## MCP Resources
- [ ] `binary://metadata` — binary name, arch, platform, entry point, size
- [ ] `binary://functions` — full function list
- [ ] `binary://symbols` — full symbol table
- [ ] `binary://types` — all type definitions
- [ ] `binary://sections` — section list

## MCP Prompts
- [ ] `analyze-function` — "Analyze the function at {addr} and explain what it does"
- [ ] `find-crypto` — "Find cryptographic routines in this binary"
- [ ] `suggest-names` — "Suggest meaningful names for unnamed functions"
- [ ] `reverse-engineering` — "Help me reverse engineer this binary"

## Settings (BN native)
- [ ] `mcp_server.enabled` (bool, default `true`) — start server on BN load
- [ ] `mcp_server.transport` (enum: `"stdio"` / `"http"`, default `"stdio"`)
- [ ] `mcp_server.http_port` (int, default `9090`) — port for HTTP transport
- [ ] `mcp_server.api_key` (string, default `""`) — API key for HTTP auth; empty = no auth

## API (`api.py`)
- [ ] `start_server(bv, *, transport=None, port=None) -> MCPServer`
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
- Stdio transport: MCP client spawns BN as subprocess, communicates via stdin/stdout
- HTTP transport: MCP client connects to BN's HTTP endpoint (for remote/headless use)
- Write tools should be optional/configurable — some users may want read-only MCP
- Consider: tool descriptions should be detailed so the AI client knows how to use them
