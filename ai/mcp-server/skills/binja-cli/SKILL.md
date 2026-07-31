---
name: binja-cli
description: Use the `bn` CLI to read, annotate, and patch a live Binary Ninja session from a shell -- list functions/symbols/types/sections/imports/exports/strings, inspect a function's disassembly/IL, rename/comment/retype/patch, capture a screenshot, and check server connectivity -- whenever you have bash access and a `bn` command (or `scripts/bn` in this skill) instead of, or alongside, MCP tools. Use when reverse engineering a binary, hunting for specific functions/strings/imports, documenting findings, patching bytes, or checking whether the MCP server and its commands are actually reachable.
---

`bn` is a thin client for a running Binary Ninja MCP server (binja-mcp) --
every subcommand is one call to the same server other MCP clients use, just
shaped for a shell instead of a tool-call protocol. Run `bn --help` for the
full subcommand list and `bn <subcommand> --help` for a subcommand's own
options -- that's the actual documentation; don't guess flags.

**Check `bn health` first if anything's unclear.** It reports whether the
server is reachable, whether your API key is valid, and exactly which
commands are enabled right now (server settings gate categories the same
way they do for MCP clients -- `--help` always shows the full set
regardless of what's actually turned on). A command that isn't listed by
`health` is a settings problem on the BN side, not something to route
around.

## Core workflow

Everything defaults to real JSON (`--format json`, reads `structuredContent`
-- not a re-parse of any text) since that's what most agents want to
consume directly. Pass `--format text` for plain, tab-separated text on
stdout instead -- pipe it through `grep`/`jq -R -s -r`/`cut`/`awk` like any
other CLI output.

**Get oriented.** `bn list functions` / `bn list symbols` / `bn list
strings` / `bn list imports` / `bn list exports` for an overview. Add
`--filter <pattern>` (substring or regex, matched against name -- or
value, for strings) to narrow before it ever reaches your context, e.g.
`bn list functions --filter '^sub_'`. `--fields name,addr` narrows/reorders
columns; `--limit`/`--offset` page through the *filtered* set.

**Understand one function.** `bn function <name-or-addr>` for disassembly;
`--il-level hlil` (or `mlil`/`llil`/`*_ssa`) for IL instead.

**Multiple binaries open.** `bn select <index>` pins which binary
subsequent calls target, persisting server-side until changed. Without an
explicit selection, calls default to index 0 rather than whatever's
focused in BN's GUI -- deterministic for a headless/scripted session. Pass
`--binary <index>` on any single command to target one without changing
the pinned selection.

**Which binary a call ran against** is always identified, but the shape
depends on `--format`: in JSON (the default) it's a `"target"` field in the
output object; in `--format text` it's instead a leading `#binary ...` line
rerouted to **stderr**, not stdout -- informational, safe to ignore, and it
won't show up in anything you pipe from stdout. Comes from
`mcp_server.echo_target_enabled` (default on).

**Document findings.** `bn rename-function <addr> <name>` / `bn
rename-symbol <addr> <name>` once confident, `bn comment <addr> <text>` /
`bn function-comment <addr> <text>` for reasoning, `bn create-struct
"struct node { int32_t id; };"` / `bn load-header <path>` / `bn set-type
<addr> <type_name>` to recover layouts as real types instead of raw
offsets, `bn create-function <addr>` if BN's own analysis missed one.

**Patch and test a hypothesis.** `bn patch-asm <addr> <assembly>`
(assembled for you) or `bn edit-hex <addr> <hex>` (raw bytes) -- needs
`destructive_write_enabled`. These are real byte writes, not undo-tracked
metadata; confirm with the user first, same as over MCP. `bn undo [--steps
N]` reverts BN's *whole* undo stack, including the human's own manual
edits, not just `bn`-made ones -- needs `undo_enabled` (off by default).

**Visual check.** `bn screenshot [--out path]` saves the current BN window
as a PNG (default `./bn-screenshot.png`) -- needs `screenshot_enabled`.
There's no way to view an image inline in a terminal, so this writes a file
rather than printing anything meaningful with `--format json`.

**Look things up / automate.** `bn search-docs <pattern>` searches Binary
Ninja's own Python API; `bn read-logs` reads BN's log console; `bn
create-snippet <name> <script>` / `bn list-snippets` manage BN's Snippet
Manager -- needs `scripting_enabled`.

## What's not here

Debugger control (`launch`, breakpoints, `step_into`/`step_over`, `resume`,
`kill_process`, `restart`) and script/snippet *execution*
(`execute_script`, `load_script`, `run_snippet`, plus their
`get_script_status`/`cancel_script` job-control) aren't wrapped by this
CLI -- both control a running process or execute arbitrary code, which
needs session/state handling well beyond a stateless one-call-per-process
CLI, and is deliberately out of scope for now (see ADR-0038's "Update"
section). Use the MCP tools directly for those (see the `binja-mcp`
skill), or `bn`'s connection info (`bn health`) with your own script.
Cross-cutting name/string search across every kind at once is `search`
over MCP; for one specific kind, `bn list <kind> --filter` is usually a
better fit.
