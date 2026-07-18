---
name: binja-mcp
description: Use Binary Ninja's live MCP server (binja-mcp) to read, annotate, patch, script, or debug a binary through a running BN session. Use when reverse engineering a binary, analyzing functions/xrefs/strings/types, renaming or commenting in Binary Ninja, patching bytes or assembly, automating BN with a script or snippet, or debugging a process under BN's debugger — whenever binja-mcp tools (get_function, rename_function, execute_script, launch, ...) are on the tool list.
---

binja-mcp exposes a running Binary Ninja session over MCP. Tool availability is gated by BN settings (`mcp_server.*_enabled`) — a tool missing from your tool list means its category is off, not broken; tell the user to flip the setting (Edit → Preferences → Settings in BN, or the `mcp_server.<category>_enabled` key) and restart the server (Plugins → MCP Server → Stop Server / Start Server), it does not take effect live.

## Tool tiers

| Tier | Default | Tools |
|---|---|---|
| Read | always on | `get_function`, `get_functions`, `get_symbols`, `get_xrefs_to`, `get_xrefs_from`, `get_types`, `get_type`, `get_data`, `get_strings`, `get_sections`, `get_imports`, `get_exports`, `search` |
| Write (safe) | on | `rename_function`, `rename_symbol`, `set_comment`, `set_function_comment`, `create_struct`, `load_header`, `set_type`, `create_function` |
| Undo | **off** | `undo_action(steps)` — reverts BN's *whole* undo stack, including the human's own manual edits, not just tool-made ones |
| Write (destructive) | **off** | `patch_asm`, `edit_hex` — writes real binary bytes |
| Scripting | **off** | `execute_script`, `load_script`, `get_script_status`, `cancel_script`, `search_docs`, `read_logs`, `create_snippet`, `list_snippets`, `run_snippet` |
| Debugging | **off** | `launch`, `set_breakpoint`, `resume`, `run_until`, `step_into`, `step_over`, `step_return`, `kill_process`, `restart` |
| GUI | **off** | `capture_screenshot` |
| Admin | always on | `select_binary(index)`, `load_binary(path)` |

Resources: `binary://metadata`, `binary://functions`, `binary://symbols`, `binary://types`, `binary://sections`, `binary://selected`, `program://binaries`, `program://plugins`.

Treat `patch_asm`/`edit_hex`/debugging tools as risky actions on real program state — confirm with the user before invoking, same as any other hard-to-reverse action.

## Common scenarios

**Get oriented in an unfamiliar binary.** `binary://metadata` for arch/entry/size, then `get_functions`, `get_symbols`, `get_strings`, `get_imports`/`get_exports` for an overview. Equivalent to sending yourself the `reverse-engineering` prompt.

**Understand one function.** `get_function(addr, il_level="hlil")` for readable pseudocode (fall back to `mlil`/`llil` for tight codegen questions), then `get_xrefs_to`/`get_xrefs_from` for callers/callees and `get_strings`/`get_data` for referenced constants. Equivalent to the `analyze-function` prompt.

**Hunt for crypto.** `search` for algorithm names and telltale constants (S-boxes, IV values), `get_imports` for crypto library calls, `get_function` on candidates. Equivalent to the `find-crypto` prompt.

**Document findings.** `rename_function`/`rename_symbol` once confident, `set_comment`/`set_function_comment` for reasoning, `create_struct`/`load_header`/`set_type` to recover recovered layouts as real types instead of raw offsets. Equivalent to the `suggest-names` prompt for the renaming pass.

**Patch and test a hypothesis.** `patch_asm(addr, assembly)` (assembled for you) or `edit_hex(addr, hex)` (raw bytes) — needs `destructive_write_enabled`. Confirm with the user first; these are real byte writes, not undo-tracked metadata.

**Automate a repeated analysis.** `execute_script`/`load_script` for one-off code, `search_docs` to look up the BN Python API instead of guessing, `read_logs` to see what a script actually printed/errored. For anything slow: pass `async_run=True` and poll `get_script_status` — tool calls are serialized server-wide, so a blocking long script freezes every other tool call (yours and any other connected client's) until it finishes. Save reusable scripts with `create_snippet` and re-run with `run_snippet`/`list_snippets` instead of re-pasting the script text.

**Debug a running process.** `launch()`, then set breakpoints. PIE binaries rebase on launch — addresses from `get_function` taken *before* `launch()` are stale; re-fetch them *after* `launch()` before `set_breakpoint`/`run_until`, or the breakpoint silently misses and the process just runs to completion. Then `step_into`/`step_over`/`step_return`/`resume`, `kill_process`/`restart` to end/reset the session.

**Multiple binaries open.** Tools operate on whichever binary is selected/focused (`binary://selected`). If more than one is open (`program://binaries`), call `select_binary(index)` explicitly before other tools rather than relying on GUI focus — otherwise you can silently read or write the wrong binary.

**Visual check.** `capture_screenshot()` when you need to see BN's actual GUI state (needs `screenshot_enabled`).

## Interacting with the user

**Ground ambiguous references, don't guess.** When the user points at something without naming it precisely — "this function", "what I'm looking at", "that highlighted block", "why is it red" — resolve it from live state instead of inferring from conversation text alone. Check `binary://selected` for the focused binary/tab, and if the reference is inherently visual (layout, color, a dialog, a graph edge, "what does this look like") call `capture_screenshot()` before answering. One screenshot call is cheaper and more accurate than a wrong guess followed by a correction round-trip. If `screenshot_enabled` is off and you need it, say so and ask the user to enable it or describe what they mean, rather than guessing.

**Resolve vague targets before writing.** "Rename this", "patch that call", "comment the loop" without an explicit address — find the target yourself first (`search`, `get_functions`, `get_xrefs_to/from`, or a screenshot if it's about on-screen position) and state what you resolved it to before calling a write tool. Don't silently write to a guessed address.

**Confirm before anything hard to reverse.** `patch_asm`/`edit_hex` (real byte writes), `undo_action` (reverts the human's own manual edits too, not just tool changes), and debugger control (`launch`, `kill_process`, `restart`, breakpoints that will run/kill the real process) all change state the user didn't explicitly ask to change in that exact call — say what you're about to do and wait for a go-ahead, don't chain them into a plan and execute silently.

**A missing tool is a settings problem, not a workaround prompt.** If a tool you need isn't in your tool list, that category is disabled — tell the user which `mcp_server.*_enabled` setting to flip and that the server needs a restart. Don't try to route around it (e.g. hand-crafting bytes via `set_type`, or asking the user to do it manually) unless they ask you to.
