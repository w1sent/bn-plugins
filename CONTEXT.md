# Reverse Engineering Plugin Suite

A monorepo of Binary Ninja plugins that extend the platform with new
architecture/runtime support, AI-driven database enrichment, and usability
improvements. Plugins share a common `core/` library but ship as
self-contained, independently-updateable install trees.

## Language

**Plugin**:
A single Binary Ninja extension that registers itself via BN's plugin API
and lives as one installable unit under `frameworks/`, `ai/`, or `ux/`.
_Avoid_: Extension, add-on, module.

**Framework plugin**:
A plugin in `frameworks/` that teaches Binary Ninja to decode a new
instruction set, language runtime, or virtual machine (e.g. Flutter/Dart,
.NET CLR, custom VM bytecode). May provide an `Architecture` subclass (for
new machine code / VM bytecode), a `BinaryView` subclass (for runtime
snapshot formats), analysis passes (for metadata enrichment), or any
combination thereof — whichever fits the target's scope. Owns its vendored
copy of `core/` and its own pinned Python deps in `.deps/`.
_Avoid_: Backend, platform plugin, architecture plugin.

**AI plugin**:
A plugin in `ai/` that uses an LLM agent (langchain/deepagents) to enrich the
BN database — auto-rename, struct suggestion, function summarization, etc.
_Avoid_: Assistant, copilot.

**UX plugin**:
A plugin in `ux/` that improves Binary Ninja's day-to-day usability
(hotkeys, custom views, navigation, annotation UX) without adding analysis
intelligence or new targets.
_Avoid_: Helper, QoL plugin, convenience plugin.

**core**:
The shared, leaf-utility library (`core/`) consumed by every plugin. Pure
helpers built only on the Binary Ninja API and the Python stdlib — no
third-party deps. Vendored per-plugin on install so each plugin pins the
version of `core/` it was built against.
_Avoid_: common, lib, shared.

**Vendored deps**:
The set of third-party Python packages a plugin installs into its own
`.deps/` directory at install time, isolated from every other plugin's
deps. Lets one plugin bump langchain without touching the others.
_Avoid_: bundled deps, frozen deps.

**Installer**:
The script in `scripts/` that materializes plugins into Binary Ninja's
plugin folder. Supports `--copy` (default, for end users) and `--link`
(symlink, for development) modes and an interactive selection prompt that
defaults to installing all plugins.
_Avoid_: setup script, bootstrap.

**Install tree**:
The on-disk result of installing one plugin into BN's plugin folder: the
plugin's source, a vendored copy of `core/`, and a populated `.deps/`
directory. Self-contained and version-independent of other install trees.
_Avoid_: deployment, install artifact.

### node-canvas (`ux/node-canvas`)

**Canvas**:
A user-curated, freeform graph workspace persisted per-binary in BN's
metadata store. Nodes are placed and grouped by hand, or dropped in via
auto-populate; the canvas as a whole is never auto-laid-out.
_Avoid_: Graph, diagram, workspace.

**Node**:
An entry on a Canvas, optionally bound to a BN address. An address-bound
Node resolves its label live from BN's current analysis rather than
storing a frozen string.
_Avoid_: Vertex, item.

**Unresolved Node**:
An address-bound Node whose address no longer resolves to a valid BN
entity (e.g. the function was deleted). Falls back to displaying the raw
address with a distinguishing prefix symbol, and shows a toast instead of
navigating on double-click.
_Avoid_: Broken node, stale node, dead node.

**Edge**:
A directed connection between two Nodes on a Canvas, with independently
settable color and thickness.
_Avoid_: Link, connection, arrow.

**Group**:
A named, color-coded, collapsible cluster of Nodes and/or other Groups.
Collapsing a Group cascades to collapse everything nested within it,
reducing it to a single box with one aggregate Edge per external
connection point; expanding restores each child's own last collapse
state.
_Avoid_: Cluster, bundle, container.

**Legend**:
A Canvas-level list of (color, label) pairs, registered explicitly and
independently of which Nodes/Edges/Groups currently use that color — a
color's meaning is intentional metadata, not inferred by scanning.
_Avoid_: Key, color map.

## References

### Binary Ninja API

- **Local (preferred):** `/Applications/Binary Ninja.app/Contents/Resources/api-docs/`
- **Online:** <https://docs.binary.ninja/dev/index.html>

### langchain

- **Reference:** <https://reference.langchain.com/python/langchain/overview>
- **Docs:** <https://docs.langchain.com/oss/python/langchain/overview>

### deepagents

- **Docs:** <https://docs.langchain.com/oss/python/deepagents/overview>
- **Reference:** <https://reference.langchain.com/python/deepagents>

## Programming

**Python** is the primary language for all plugins and `core/`. Use **C++**
only when performance demands it, and expose it as a Python module so
plugins consume it through the same Python interface.

## Developing and testing plugins

Agents developing or debugging a plugin should use the `binja-mcp` MCP
server to interact with a live Binary Ninja instance and test the plugin
themselves, rather than relying on static reading of the code. It exposes
API-search (`search_docs`) and an `execute_script` command for iterating
against the live BN API interactively. `binja-mcp` requires a running BN
instance — if one isn't already up, start it first before using the other
`binja-mcp` tools.