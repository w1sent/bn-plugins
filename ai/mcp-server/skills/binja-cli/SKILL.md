---
name: binja-cli
description: Use the `bn` CLI to read a live Binary Ninja session from a shell -- list functions/symbols/types/sections/imports/exports/strings, inspect a function's disassembly/IL, and check server connectivity -- whenever you have bash access and a `bn` command (or `scripts/bn` in this skill) instead of, or alongside, MCP tools. Use when reverse engineering a binary, hunting for specific functions/strings/imports, or checking whether the MCP server and its commands are actually reachable.
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

Everything defaults to plain, tab-separated text on stdout -- pipe it
through `grep`/`jq -R -s -r`/`cut`/`awk` like any other CLI output. Pass
`--format json` on any command for real JSON instead (reads
`structuredContent`, not a re-parse of the text).

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

**A leading `#binary ...` line on stderr, not stdout**, names which binary
a call actually ran against -- informational, safe to ignore; it won't
show up in anything you pipe from stdout. Comes from
`mcp_server.echo_target_enabled` (default on).

## What's not here

Write/patch/debug/script tools (`rename_function`, `patch_asm`, `launch`,
`execute_script`, ...) aren't wrapped by this CLI yet -- for those, use the
MCP tools directly (see the `binja-mcp` skill) or `bn`'s connection info
with your own script. Cross-cutting name/string search across every kind
at once is `search` over MCP; for one specific kind, `bn list <kind>
--filter` is usually a better fit.
