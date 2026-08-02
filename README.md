# Reverse Engineering Plugin Suite

A monorepo of Binary Ninja plugins that extend the platform with new
architecture/runtime support, AI-driven database enrichment, and usability
improvements. Plugins share a common `core/` library but ship as
self-contained, independently-updateable install trees — each plugin
vendors its own copy of `core/` and pins its own third-party dependencies,
so upgrading one plugin never touches another's.

See `CONTEXT.md` for the project's glossary (what "plugin", "framework
plugin", "core", "install tree", etc. mean here) and `docs/adr/` for the
design decisions behind specific features.

## Layout

```
ai/          AI-driven database enrichment plugins (langchain/deepagents)
frameworks/  New architecture/runtime/VM support for Binary Ninja
ux/          Usability improvements (custom views, navigation, annotation)
core/        Shared leaf-utility library, vendored per-plugin on install
scripts/     install.py and other repo-management scripts
docs/adr/    Architecture decision records
testcases/   Small built binaries used by plugin test suites
tests/       Tests for core/ itself
```

## Plugins

### AI (`ai/`)

| Plugin | Description |
|---|---|
| [`agentic-triage`](ai/agentic-triage/README.md) | AI-generated sample context prompt (deterministic baseline + optional AI enhancer), viewable/editable in a dedicated Agentic Triage view. Feeds the shared context every other AI plugin reads. |
| [`auto-rename`](ai/auto-rename/README.md) | AI-driven function and variable renaming, with configurable bulk-rename ordering/concurrency and scoped (local-neighborhood) runs. |
| [`suggest-structs`](ai/suggest-structs/README.md) | AI-driven struct suggestion from pointer access patterns, seeded by a deterministic HLIL skeleton pass. |
| [`mcp-server`](ai/mcp-server/README.md) | Exposes Binary Ninja's database as an MCP server so external AI tools (Claude Code, Codex, OpenCode, DeepAgents, ...) can read, write, script, and debug through a real, running BN session. |

### Frameworks (`frameworks/`)

| Plugin | Description |
|---|---|
| [`dotnet-native-aot`](frameworks/dotnet-native-aot/README.md) | Recovers .NET NativeAOT runtime metadata (MethodTable/EEType type hierarchy, virtual methods, frozen strings/arrays/boxed values) with no IL, CLR, or symbols required. |

The rest of `frameworks/` (`compiled-python`, `dotnet`, `flutter`, `go`,
`react-native`, `swift`, `unity-il2cpp`, `wasm`) are planning-stage: each
has only a `TODO.md` describing intended scope, no code yet.

### UX (`ux/`)

| Plugin | Description |
|---|---|
| [`node-canvas`](ux/node-canvas/README.md) | A user-curated, freeform graph workspace: hand-place and group nodes bound to BN addresses, auto-populate call trees and xref graphs, and persist/export/import the canvas alongside the binary. |
| [`hex-visualizer`](ux/hex-visualizer/README.md) | A sidebar inspector panel driven by the hex/linear-view selection: media preview (with full-file carving from a partial selection) for image formats, plus a hex/ASCII/common-type data-inspector table. |

`ux/frida` and `ux/joern` are likewise planning-stage (`TODO.md` only).
`ux/diff` was removed — see [ADR-0030](docs/adr/0030-diff-matching-and-ui-design.md)
("superseded" note at the top) — since Binary Ninja 6.0 is planned to ship
its own native diffing tool.

## Installing

```
python scripts/install.py                 # install all plugins (copy mode)
python scripts/install.py --link          # install all plugins (symlink, for development)
python scripts/install.py --interactive   # choose which plugins to install
python scripts/install.py --plugin-dir PATH  # override BN's plugin folder
python scripts/install.py --install-external # also install/update third-party plugins (see below)
```

Copy mode vendors a fresh copy of `core/` and installs each plugin's pinned
`requirements.txt` into its own `.deps/` directory; link mode symlinks
`core/` and the plugin's own files instead, so local edits take effect
without reinstalling (adding a new *file* still requires rerunning the
installer, since only existing symlinks are refreshed otherwise). Restart
Binary Ninja after installing or reinstalling.

`--install-external` additionally installs/updates a fixed set of
third-party Vector 35 plugins that aren't part of this project -- Blob
Extractor, Kaitai UI Plugin, Snippets UI Plugin, and Tanto -- as plain git
clones (`git pull` if already present) directly into BN's plugin folder,
including installing that clone's own `requirements.txt` into its `.deps/`
the same way this repo's own plugins do. They're untouched by a plain
`install.py` run and unaffected by `--link`.

Each AI plugin auto-creates `~/.binaryninja/ai-config.json` (LLM provider
config, shared across AI plugins) on first use if it doesn't already exist,
defaulting to a local Ollama instance.

## Requirements

- Binary Ninja build 3164 or newer
- Python 3 (matching Binary Ninja's own Python environment)
- AI plugins additionally need `langchain`/`deepagents` and a reachable LLM
  provider (local Ollama by default, or a cloud provider configured in
  `ai-config.json`)

## Development

- Each plugin is independent (`docs/adr/0014`) — no plugin imports another
  plugin's code, only its own vendored `core/`.
- `api.py` is each plugin's canonical, documented entry point
  (`docs/adr/0019`); UI commands are thin wrappers around it.
- Settings are registered via BN's native Settings API and documented in
  each plugin's own `README.md` (`docs/adr/0017`).
- Tests are per-plugin under `<plugin>/tests/`, plus shared `testcases/`
  binaries (`docs/adr/0009`); most GUI-plugin tests run inside a live BN
  session (`Tools > Run Script`), not headlessly.
- See `docs/adr/` for the reasoning behind these and other conventions.
