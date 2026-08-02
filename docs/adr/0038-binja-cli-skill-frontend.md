# binja-mcp: add a CLI+Skill front end alongside the MCP server

`ai/mcp-server` currently has one front end: an MCP server with ~50 tools
(see its README). That works for MCP-native clients, but two problems came
up while planning integration with `pi` (https://pi.dev), a minimal agent
harness that deliberately has no built-in MCP support and instead favors
"well-integrated extensions" (native TypeScript, via `pi.registerTool`) or
"CLI tools with READMEs" fronted by on-demand Skills:

- Several read tools return unfilterable bulk data server-side (e.g. the
  `binary://functions` resource calls `get_functions(limit=1_000_000,
  offset=0)`) — a client has no way to narrow the result before it lands in
  the model's context.
- MCP itself has no skill-registration primitive; today's single
  `skills/binja-mcp/SKILL.md` is a plain file copy for Claude Code, not
  something the protocol understands, and it's loaded as one all-or-nothing
  unit regardless of what the task actually needs.

Decided design below, arrived at by walking each fork explicitly rather than
guessing. Nothing in `ai/mcp-server` is changed yet — this is the agreed
design to build against, not a report of what shipped.

## Scope: additive, one shared tool design, not two

The MCP server stays as-is for its existing clients (Claude Code, Codex,
OpenCode, DeepAgents). A new CLI+Skill front end is added alongside it, not
instead of it. Backward compatibility with today's MCP tool names/shapes is
explicitly *not* a constraint — the tool surface itself gets redesigned once
(see below) and both front ends share that one redesign, rather than the CLI
getting a clean composable design while MCP keeps the old one. Maintaining
two divergent tool designs was ruled out as not worth the ongoing cost of
keeping them behaviorally in sync.

## Primary interface: CLI + Skill, not a native pi Extension

Pi supports two integration mechanisms: native TypeScript Extensions
(`pi.registerTool`, typed Typebox params, and a `content`/`details` split on
tool results — `details` persists as session state without ever entering the
LLM's context, which is a genuinely strong answer to bloat) or CLI binaries
fronted by a Skill (`SKILL.md` + a `scripts/` dir), discovered progressively
— only name+description sit in the system prompt until the agent `read`s the
full skill.

CLI+Skill was chosen as primary because it's harness-agnostic: a TypeScript
Extension only runs inside pi, while a CLI works anywhere with bash access —
including Claude Code, which already supports the same Skill convention pi
does. Given the explicit goal of backporting pi's design strengths to other
harnesses (not just optimizing for pi), the redesign work needs to land
somewhere portable. A thin native pi Extension may be added later purely as
a convenience wrapper *around* the same CLI (nicer TUI rendering, etc.), but
it is not where the actual tool design lives.

## Transport: the CLI is an MCP client, not a second HTTP surface

The plugin's plain functions (`reading.py`, `writing.py`, etc.) only run
inside BN's own process — they call BN's Python API directly and require
`binaryninjaui` calls marshalled onto BN's main thread. The CLI is
necessarily a separate process, so "shared core" for the CLI means "hits the
same server-side logic over the wire," not a direct import.

Rather than standing up a second, simpler HTTP surface (e.g. plain
`GET /list?...` routes) that shares the underlying functions but duplicates
routing/schema/auth wiring against FastMCP, the CLI is just a thin MCP
client: argv → MCP tool-call request → the existing `/mcp` endpoint, same
Bearer auth, same (redesigned) tool set → JSON-RPC response → rendered as
text. One protocol, one implementation per tool. This also rides along with
the in-flight `mcp` 2.0 migration noted in the plugin's README, which moves
the protocol to stateless request/response — the shape a fresh CLI process
per invocation already wants.

A useful consequence: because the CLI is a real MCP client, it automatically
inherits today's category gating (`mcp_server.*_enabled`). A disabled
category is genuinely uncallable through the CLI too, not just hidden.

## Tool surface: consolidate listing tools, keep action tools distinct

Applies specifically to the *listing/query-shaped* read tools —
`get_functions`, `get_symbols`, `get_types`, `get_sections`, `get_imports`,
`get_exports`, `get_strings` — which collapse into one `list <kind>`
primitive sharing one filter/fields/limit/offset convention instead of each
reinventing its own ad hoc params (and, for several of them, having no
pagination at all today).

Action-shaped tools — `rename_function`, `set_comment`, `patch_asm`,
`launch`, `step_into`, `execute_script`, and friends — stay as distinct,
clearly-named commands. Folding a rename or a breakpoint-set into a generic
verb wouldn't reduce bloat; it would just obscure what's happening for no
benefit.

## Filtering: minimal, not a query DSL

Built-in filtering is deliberately small: a name regex, field projection
(`--fields`), and `limit`/`offset` — essentially today's `search(pattern)`
generalized across all listing kinds. No bespoke predicate language (e.g.
`name~sub_ and addr>0x1000`) was built. Rationale: it's mostly redundant
with what CLI users already get for free by piping to `jq`, and for
anything the minimal filter can't express, the existing scripting tools
(`execute_script`/`run_snippet`) already give full BN API access, which is
strictly more powerful than any query language we'd design here.

This is also the structural reason CLI and MCP need real built-in filtering
rather than "just pipe it": an MCP tool call has no shell stage between the
tool's return value and the LLM's context, so whatever isn't filtered
server-side lands in context whole. A CLI's stdout, by contrast, can be
filtered by the calling shell *before* it becomes a tool result — the
unfiltered data never touches context. The built-in filter is what MCP relies
on entirely; the CLI gets it too, plus `jq`/`grep` on top for anything fancier.

## Output format: text on the MCP wire everywhere, JSON as the CLI's own default

Every MCP tool's `content` is plain text: one header line, then one record
per line, fields separated by a single tab, no alignment padding (padding
spaces are pure token cost with no information gain for an LLM reader,
unlike a human terminal). This applies to every tool in every module —
`reading.py`/`listing.py`/`administration.py`/`writing.py`/`patching.py`/
`undo.py`/`debugging.py`/`scripting.py` — not just the read/list tier;
disassembly in particular is already text-shaped data, and wrapping each
instruction line in `{"address": ..., "text": ...}` is pure JSON
key-repetition overhead for no gain. The one genuine exception is
`capture_screenshot` (`gui.py`): image bytes have no meaningful text form,
so it returns MCP's `Image` content type instead — not an oversight, just
nothing for this principle to apply to.

`content` is never JSON, and `format` is deliberately *not* a parameter on
any MCP tool — an MCP caller has no shell to consume JSON with, so the
param would be dead weight on every single call for a case that almost
never applies. `structuredContent` (a real, separate field on every tool
result, which a plain MCP client simply doesn't render) carries the same
data as actual JSON regardless — that's what the CLI's `--format json`
reads. See "Update: CLI JSON-by-default" below for how the CLI's own
default (not MCP's wire behavior) later changed.

## Binary targeting: fixed default, no ambient "last selected" state

When `--binary` isn't given, the CLI targets index 0 (or the sole open
binary) — not "whatever was last selected," which is today's MCP behavior
via `binary_context.py` and `select_binary`. A fixed default removes an
entire class of stale-state bugs (an earlier `select` call, forgotten,
silently redirecting a much later, unrelated call) rather than just making
them visible after the fact.

`select <id>` remains available as an opt-in convenience for pinning a
non-default target across a multi-binary CLI session without repeating
`--binary` on every call. Every call also echoes which binary it targeted —
on **stderr**, not stdout, so `bn list functions | jq ...` stays clean and
requires no stripping step — toggleable via a BN setting alongside the
existing `mcp_server.*_enabled` gates, in case the line is unwanted.

## Server discovery: connection file first, explicit override for remote

Precedence, highest wins: **CLI flag** (`--server`/`--api-key`) → **env
vars** (`BN_MCP_URL`/`BN_MCP_API_KEY`) → **local connection file** the BN
plugin writes on server start (host/port/API key — it already tracks this
state in memory via `get_server_status()`/`ensure_api_key()` in `api.py`;
this just also persists it).

The connection file is a zero-config default for the common case (BN and
the agent on the same machine — the normal case for a GUI RE tool you're
actively looking at). It intentionally does not solve remote BN by itself:
that already requires deliberately opening `mcp_server.bind_address` beyond
loopback today, so requiring an equally deliberate env var/flag on the CLI
side for a remote setup matches existing friction rather than adding new
friction. Network auto-discovery for an API-keyed control plane was
rejected outright as a security downgrade, not just unnecessary complexity.

## Skill structure: one skill; `--help` for docs, `health` for live status

One skill, not several category-scoped ones. A lean `SKILL.md` covers
orientation; `bn --help` / `bn <subcommand> --help` is the actual
progressive-disclosure mechanism — static, full documentation, works
offline, and is more granular than splitting into multiple skill files
(per-subcommand, not per-category) without the awkward-boundary problem
category splitting would hit (e.g. today's PIE-rebase note genuinely spans
both reading and debugging).

`--help` is deliberately static and doesn't reflect live gating. A separate
`bn health` command is the live counterpart: checks BN reachability
(building on the transport's existing unauthenticated `/health` endpoint in
`server.py`), validates the API key, and reports which commands are
actually enabled given current BN settings — one cheap, explicit place for
both a human and an agent to check "is this usable right now" instead of
discovering gating through failed calls.

## Implementation: stdlib-only Python, installed onto PATH

The CLI's job is small — argv parsing, an HTTP POST to `/mcp` with Bearer
auth, JSON-RPC response handling, text rendering — and needs no third-party
dependencies. Measured on-machine: bare `python3` startup is ~11-17ms;
adding `argparse`+`json`+`http.client` (what the CLI actually needs) comes
to ~35-40ms; swapping in `urllib.request` instead costs ~48-52ms for no
benefit (it pulls in `ssl`/email machinery irrelevant to a loopback call) —
so `http.client` over `urllib.request` is a free ~10ms back. Against a
compiled binary's ~1-3ms process-spawn floor, that's roughly a 30ms/call
Python tax, which is dwarfed by BN-side analysis time (often 10-200ms+) and
by LLM-turn latency surrounding each tool call in the agent loop (hundreds
of ms to seconds) — not worth a second language/toolchain for right now.

Python was chosen deliberately for rapid iteration while the tool surface
itself is still being designed; a migration to Rust (or similar) for the
CLI and/or the MCP server is an explicit possible later step once the
design has stabilized, not attempted now.

The script's canonical source lives in `skills/binja-cli/scripts/bn` in this
repo (versioned alongside `SKILL.md`, same as today's pattern), but
installing the skill (`install_mcp_clients.py`, `--cli-dest`/`--no-cli`)
additionally symlinks it onto the user's `PATH` (default `~/.local/bin/bn`)
rather than leaving it reachable only via the skill directory — both the
user and any agent should be able to just run `bn` directly.

## Update: full tool coverage, CLI JSON-by-default

Two changes made after the initial build, once live testing against a real
BN session (not just unit tests) surfaced the actual gaps:

- **Every MCP tool now returns the shared text+structuredContent shape**,
  not just `reading.py`/`listing.py`/`administration.py`. The first pass
  left `writing.py`/`patching.py`/`undo.py`/`debugging.py`/`scripting.py`
  returning raw dicts (auto-JSON-dumped by FastMCP's default conversion),
  which contradicted this document's own "applies uniformly" claim above —
  a real documentation/implementation mismatch, not a deliberate scope cut.
  Fixed by converting all of them the same way.
- **The CLI now covers every non-execution tool**, not just read/list:
  `rename-function`/`rename-symbol`/`comment`/`function-comment`/
  `create-struct`/`load-header`/`set-type`/`create-function` (`writing.py`),
  `patch-asm`/`edit-hex` (`patching.py`), `undo` (`undo.py`), `screenshot`
  (`gui.py` — saves the PNG to a file, since a terminal can't render inline
  images), and `search-docs`/`read-logs`/`create-snippet`/`list-snippets`
  (`scripting.py`'s non-execution tools). Still deliberately uncovered:
  all of `debugging.py` (`launch`/breakpoints/step/resume/kill/restart) and
  `scripting.py`'s `execute_script`/`load_script`/`run_snippet`/
  `get_script_status`/`cancel_script` — these control a running process or
  execute arbitrary code, a materially bigger and riskier CLI-ergonomics
  problem (session/state semantics, not just a stateless request/response)
  than everything else here, and out of scope for this pass. Raw MCP tool
  calls remain the way to reach them for now.
- **The CLI's own default flipped from text to `--format json`** — most
  agentic callers consume JSON directly regardless of what's easiest for a
  human to eyeball, so defaulting to it removes a flag most callers would
  pass anyway. `--format text` is still available for anyone piping into
  `jq`/`grep`/`awk` or just reading it themselves. This is purely the CLI's
  own default; it doesn't change anything about MCP's wire behavior above —
  `content` is still always text, `structuredContent` is still where the
  CLI's JSON output actually comes from, and `format` is still not an MCP
  tool parameter.

## Update: `execute_script`/`load_script`/`run_snippet` CLI coverage

The previous update left script *execution* uncovered pending a
session/polling design (debugger control is still uncovered — see that
section above). The server side already had everything needed: `async_run`
on `execute_script`/`load_script`/`run_snippet` picks sync (blocks under the
server's global tool-call lock, matching a plain request/response) vs. async
(runs on its own thread, returns a `job_id` for `get_script_status`/
`cancel_script` to poll/cancel). The CLI adds no new server-side surface —
it's a thin client over that existing split, plus one CLI-only convenience:

- **Sync stays the default** — one HTTP request held open until the script
  finishes, fitting the same one-call-per-process shape as every other
  command. The connection's normal ~30s socket timeout is bumped to a
  `--timeout` flag (default 300s) for this case specifically, since a
  script can legitimately run far longer than any other tool call; hitting
  that timeout raises a clean error naming `--async`/`--wait` as the way
  out (the script itself keeps running server-side either way — sync mode
  doesn't cancel on a client-side timeout, it just stops waiting).
- **`--async` is fire-and-forget** — prints the `job_id` and exits
  immediately, mirroring the MCP tool's own `async_run=True` shape exactly.
- **`--wait` is a CLI-only addition, not a new server capability** — runs
  async under the hood, then polls `get_script_status` client-side every
  `--interval` seconds until it finishes. The reason it's worth adding
  despite being "just" repeated polling: Ctrl-C during `--wait` detaches
  cleanly (the job keeps running server-side, reattach later with `bn job
  wait <job_id>`) instead of the blunt "kill the socket" a plain Ctrl-C
  gives you in sync mode. Same rationale as `screenshot` writing a PNG file
  client-side — a legitimate CLI-side convenience layered on an unchanged
  tool call, not a second implementation of the underlying behavior.
- **`bn job status`/`bn job wait`/`bn job cancel`** thinly wrap
  `get_script_status`/(the `--wait` loop)/`cancel_script`, grouped the same
  way `bn instance <cmd>` groups local process control — a natural fit
  since all three take the same `job_id` produced by `--async`.

`load-script`/`run-snippet` share this exact design (same `_run_script_like`
dispatch in the CLI) since they're the same server-side execution path
sourced from a file or a saved snippet instead of literal script text.

## Considered and rejected

- **Native pi TypeScript Extension as the primary interface** — rejected as
  *primary*: pi-specific, doesn't back-port to Claude Code/Codex/OpenCode/
  DeepAgents. May return later as a thin convenience wrapper over the CLI.
- **A second bespoke HTTP/REST surface for the CLI** — rejected; duplicates
  auth/routing/schema against FastMCP for no benefit once the tool set is
  already being redesigned once, shared.
- **A predicate/query DSL for filtering** — rejected; redundant with `jq` on
  the CLI side, and the real complaint (no filtering at all) is covered by
  regex + field projection + limit/offset.
- **Compiled Go/Rust/TS CLI for near-zero startup overhead** — rejected for
  now; measured ~30ms/call Python tax is dwarfed by BN-side work and
  surrounding LLM-turn latency. Revisit once the design stabilizes (possible
  shared Rust rewrite of CLI + MCP server both).
- **Ambient "last selected binary" as the CLI default** — rejected; a fixed
  default (index 0) removes a class of stale-state bugs outright rather than
  just surfacing them after the fact via a header/flag.
- **JSON as an MCP tool parameter, or as MCP's `content` format at all** —
  rejected, still true after the CLI's own default later flipped (see
  "Update" above): JSON's per-record key repetition is pure token cost for
  callers with no shell to pipe it through, and `structuredContent` already
  carries the same data for anything that specifically wants real JSON.
