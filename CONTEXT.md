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