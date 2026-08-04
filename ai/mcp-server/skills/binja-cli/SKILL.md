---
name: binja-cli
description: Use the `bn` CLI to read, annotate, and patch a live Binary Ninja session from a shell -- list functions/symbols/types/sections/imports/exports/strings, inspect a function's disassembly/IL, trace cross-references and search names/strings, look up a type's definition, rename/comment/retype/patch, capture a screenshot, check server connectivity, and start/close/restart the Binary Ninja application itself -- whenever you have bash access and a `bn` command (or `scripts/bn` in this skill) instead of, or alongside, MCP tools. Use when reverse engineering a binary, hunting for specific functions/strings/imports, tracing what calls or is called by an address, documenting findings, patching bytes, launching or relaunching Binary Ninja, or checking whether the MCP server and its commands are actually reachable.
---

`bn` is a thin client for a running Binary Ninja MCP server (binja-mcp) --
every subcommand is one call to the same server other MCP clients use, just
shaped for a shell instead of a tool-call protocol. Run `bn --help` for the
full subcommand list and `bn <subcommand> --help` for a subcommand's own
options -- that's the actual documentation; don't guess flags.

**Check `bn health` first if anything's unclear.** It reports whether a BN
process is running at all, whether its server is reachable, whether your
API key is valid, and exactly which commands are enabled right now (server
settings gate categories the same way they do for MCP clients -- `--help`
always shows the full set regardless of what's actually turned on). A
command that isn't listed by `health` is a settings problem on the BN side,
not something to route around; "process: not running" or "process:
unknown" (no local connection file) means there's nothing to reach yet --
see `bn instance start` below.

**No BN running yet, or need to reload a plugin change?** `bn instance
start` launches the Binary Ninja application itself (local process, not an
MCP call -- there's no server to call until BN is up); `bn instance close`
sends it SIGTERM, force-killing with SIGKILL only if it hasn't exited within
`--timeout` seconds (default 15s); `bn instance restart` is the two
combined, e.g. after installing a new/changed plugin file that needs BN
relaunched to load. `bn instance save-all` saves every open binary's
analysis database (creating a `.bndb` next to the original file for one
that doesn't have one yet) -- run it before `close`/`restart` if unsaved
analysis work should survive.

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

**Trace references.** `bn xrefs-to <addr>` / `bn xrefs-from <addr>` list
code and data cross-references to/from an address, each paginated
independently via `--limit`/`--offset` (default 100/0). `bn type <name>`
gets a defined type's definition by name. `bn search <pattern>` (substring
or regex, `--limit`, default 50) searches function names, symbol names, and
defined strings all at once -- for filtering *one* specific kind instead,
prefer `bn list <kind> --filter <pattern>`.

**Dump raw bytes.** `bn hex <addr> <length>` reads bytes at an address --
`--format text` (the CLI's `--format json` default won't render as nicely)
shows a classic offset/hex/ASCII view; `--format json` just gives the plain
hex string.

**Multiple binaries open.** `bn select <index>` pins which binary
subsequent calls target, persisting server-side until changed. Without an
explicit selection, calls default to index 0 rather than whatever's
focused in BN's GUI -- deterministic for a headless/scripted session. Pass
`--binary <index>` on any single command to target one without changing
the pinned selection.

**Open a binary or `.bndb`.** `bn load-binary <path>` opens it as a new
tab in BN's GUI (needs a GUI session -- there's no headless open yet) and
pins the selection to it, same as `bn select` afterward. Use an existing
`.bndb` path to resume a saved analysis database instead of re-analyzing
from scratch. A relative `<path>` resolves against the shell's cwd where
you ran `bn`, not BN's own working directory -- true of every `bn`
subcommand taking a file path (`load-header`, `load-script` too).

**Which binary a call ran against** is always identified, but the shape
depends on `--format`: in JSON (the default) it's a `"target"` field in the
output object; in `--format text` it's instead a leading `#binary ...` line
rerouted to **stderr**, not stdout -- informational, safe to ignore, and it
won't show up in anything you pipe from stdout. Comes from
`mcp_server.echo_target_enabled` (default on).

**Trigger re-analysis.** `bn analyze` reprocesses every function from
scratch (same as BN's GUI "Reanalyze") -- useful after `bn load-binary` or
a patch reveals code BN's own incremental analysis wouldn't otherwise catch.
Same sync-default/`--async`/`--wait` split as script execution above (no
`job_id` here though -- `--wait`/`bn analysis-status [--wait]` just poll
BN's own native analysis progress for the current binary, which works
regardless of which process triggered it).

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

**Run a script.** `bn execute-script <script>` (for multi-line scripts use
`$(cat file.py)` or shell quoting) runs arbitrary Python inside BN, with
`bv` (the current binary view) and `should_cancel()` in scope; `bn
load-script <path>` and `bn run-snippet <name>` are the same thing sourced
from a file or from BN's Snippet Manager -- needs `scripting_enabled`. All
three default to synchronous (blocks until the script finishes, `--timeout`
seconds max, default 300); pass `--async` to fire-and-forget and get back a
`job_id` immediately, or `--wait` to run async but have this process poll
until it finishes (Ctrl-C detaches without stopping the job -- it was never
tied to this process). A synchronous script also holds BN's global tool-call
lock for as long as it runs, blocking every other tool call meanwhile
(server-side, same as over MCP) -- reach for `--async`/`--wait` for
anything that isn't quick. `bn job status <job_id>` / `bn job wait
<job_id>` / `bn job cancel <job_id>` check on, wait for, or request
best-effort cancellation of a job started with `--async` (cancellation only
takes effect if the script itself calls `should_cancel()`).

## What's not here

Debugger control (`launch`, breakpoints, `step_into`/`step_over`, `resume`,
`kill_process`, `restart`) isn't wrapped by this CLI -- it controls a
running process across multiple calls, which needs session/state handling
this CLI doesn't have yet (see ADR-0038's "Update" section; script
execution got that treatment and is covered above, debugging hasn't yet).
Use the MCP tools directly for it (see the `binja-mcp` skill), or `bn`'s
connection info (`bn health`) with your own script. Cross-cutting
name/string search across every kind at once is `search` over MCP; for one
specific kind, `bn list <kind> --filter` is usually a better fit.
