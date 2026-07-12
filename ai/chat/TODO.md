# chat — AI chat bot integrated into Binary Ninja UI

## Scope
- [ ] Dockable side panel with chat interface inside BN
- [ ] Deepagents-powered agent with access to BN database tools
- [ ] Conversational: user asks questions, agent responds with analysis
- [ ] Context-aware: agent knows current binary, function, selection, cursor position
- [ ] Agent can perform read operations (disassembly, symbols, xrefs, types, data)
- [ ] Agent can perform write operations (rename, comment, create types) with user confirmation
- [ ] Chat history persists per session, exportable
- [ ] Streaming responses: agent's output appears token-by-token

## Commands
- [ ] "Open Chat" — opens the chat panel (or focuses it if already open)
- [ ] "Ask About Function" — opens chat with a pre-filled question about the current function
- [ ] "Ask About Selection" — opens chat with context about the current selection

## Chat panel UI
- [ ] Message list: user messages (right-aligned), agent messages (left-aligned)
- [ ] Input box at bottom with send button and Enter-to-send
- [ ] Agent messages support markdown rendering (code blocks, lists, bold)
- [ ] Code blocks have "Jump to address" links for addresses
- [ ] Tool calls shown as collapsible sections ("Agent is reading function `parse_header`...")
- [ ] Typing indicator while agent is working
- [ ] Clear chat button
- [ ] Export chat as markdown button
- [ ] Model/provider indicator in the panel header

## Agent tools (read)
- [ ] `get_function(name_or_addr)` — function metadata + disassembly
- [ ] `get_current_function()` — the function at the cursor
- [ ] `get_xrefs_to(addr)` — cross-references to an address
- [ ] `get_xrefs_from(addr)` — cross-references from an address
- [ ] `get_symbols(filter)` — symbols matching a filter
- [ ] `get_types()` — all user-defined types
- [ ] `get_strings(filter)` — strings matching a filter
- [ ] `get_data(addr, size)` — raw bytes at address
- [ ] `get_sections()` — binary sections
- [ ] `get_imports()` — imported functions
- [ ] `decompile(addr)` — HLIL decompilation
- [ ] `search(pattern)` — search binary for pattern

## Agent tools (write)
- [ ] `rename_function(addr, name)` — rename a function
- [ ] `rename_symbol(addr, name)` — rename a symbol
- [ ] `set_comment(addr, comment)` — set a comment
- [ ] `create_struct(name, fields)` — create a struct type
- [ ] `set_type(addr, type_name)` — apply a type
- [ ] Write operations show a confirmation in chat before applying

## Agent tools (scripting & plugin API)
- [ ] `run_script(code)` — execute arbitrary Python in BN's context, returns stdout/stderr
- [ ] `list_plugins()` — list all installed plugins with their API modules
- [ ] `get_plugin_help(plugin_name)` — get `api.help()` output for a plugin
- [ ] Agent can compose scripts that call other plugins' APIs (e.g. `from ai.auto_rename import api; api.rename_all(bv)`)
- [ ] Script execution shows a confirmation in chat before running (configurable)
- [ ] Script output displayed in chat as a code block
- [ ] Agent can iterate: run script, read output, refine script, run again

## System prompt
- [ ] Agent is a reverse engineering assistant
- [ ] Knows the binary's architecture, platform, and metadata
- [ ] Can reference current function/selection context
- [ ] Cites addresses and evidence in responses
- [ ] Suggests write operations but asks before applying (unless auto-apply is enabled)
- [ ] Can write and execute Python scripts to automate tasks
- [ ] Can discover and call other plugins' APIs via `list_plugins()` and `get_plugin_help()`
- [ ] Can chain plugin operations: e.g. run auto-rename, then summarize renamed functions

## Settings (BN native)
- [ ] `chat.provider` (string, default `""` → use ai-config default)
- [ ] `chat.mode` (enum: `"single"` / `"multi"`, default `"multi"`)
- [ ] `chat.config_path` (string, default `~/.binaryninja/chat.json`)
- [ ] `chat.auto_apply` (bool, default `false`) — apply write operations without confirmation
- [ ] `chat.max_history` (int, default `50`) — max messages to keep in context

## API (`api.py`)
- [ ] `open_chat(bv)` — opens or focuses the chat panel
- [ ] `ask(bv, question, *, provider=None) -> str` — ask a question, get response (non-UI)
- [ ] `get_history(bv) -> list[Message]`
- [ ] `clear_history(bv)`
- [ ] `api.help()`
- [ ] All functions fully type-hinted

## Dependencies
- [ ] `deepagents` pip package (vendored per-plugin)
- [ ] `langchain` pip package (vendored per-plugin)

## Notes
- This is the most user-facing AI plugin — it's the entry point for AI-assisted RE
- Streaming is important for UX — agent responses can take 10-60 seconds
- Tool calls should be visible so the user understands what the agent is doing
- Consider: agent memory across sessions (save/load conversation)
- Consider: pre-built prompt templates the user can select from a dropdown
- Consider: agent can reference results from other AI plugins (auto-rename, relevance, etc.)
