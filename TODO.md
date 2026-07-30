# TODO

## Custom RE agent harness
Build a custom agent harness optimized for reverse engineering, including both a CLI and a Binary
Ninja frontend.

## Debug-time type application script
Create a script that applies types during debugging by tracking memory locations from registers,
including following pointers into objects.

## Automate debugging in Binja
Research and implement ways to automate debugging workflows in Binary Ninja.

## RE quality-of-life snippet collection
Build a collection of snippets that improve quality of life while reverse engineering.

## Improve reachability inspection (tanto or new plugin)
Either improve tanto's usability or build a new plugin that makes it easy to inspect reachability
of variables, basic blocks, functions, etc.

## Graph-analysis QoL API
`core/graph.py` now hosts the traversal/ordering primitives lifted from `ai/auto-rename` (see
[ADR-0036](docs/adr/0036-graph-api-extraction-and-scoped-ai-runs.md)): `neighborhood`,
`order_functions`, `zero_caller_roots`. Still missing: reachability, dominators, and clustering
(for module-boundary detection) — add these incrementally, only when a concrete consumer needs
them.

## Hex-editor visualizer side panel
Done -- see [`ux/hex-visualizer`](ux/hex-visualizer/README.md) and
[ADR-0037](docs/adr/0037-hex-visualizer-inspector-panel.md). Remaining/deferred scope (video-frame
decode for ISO-BMFF containers, struct/pattern overlays, additional carveable formats) tracked in
`ux/hex-visualizer/TODO.md`.

## ADR discipline check
Add an explicit check (or at least a habit/reminder) that significant design decisions — especially
ones touching multiple AI plugins, like the AI sample-context prompt — get an ADR written in
`docs/adr` before implementation, not after.

## Test coverage for framework detection
Build a small corpus of known-binary fingerprints under `testcases/` to cover the rule-based
detection logic in `frameworks/*` (Flutter, .NET Native AOT, Go, Unity IL2CPP, etc.), so new
framework additions or rule changes don't silently regress detection of existing ones.

## Surface Joern integration in core
If `ux/joern` currently produces its own CPG-based output in isolation, build an adapter that maps
Joern's dataflow/reachability results back onto BN's own variable/basic-block/function IDs, and
surface that mapping via `core` so other plugins (e.g. reachability inspection) can reuse it instead
of reimplementing dataflow analysis.

## Frida bridge in ux/frida
Extend `ux/frida` into a two-way bridge instead of one-way script injection: stream runtime data
(hit addresses, argument values, pointer targets) from a running Frida-instrumented process back
into BN as tags/comments/types live. Feeds directly into the debug-time type application and
"automate debugging in Binja" TODOs — Frida becomes the runtime data source, BN the annotation sink.

## Diff-driven re-analysis
When `ux/diff` detects a changed function between two binary versions, auto-invalidate that
function's cached AI context/evidence and re-run auto-rename/suggest-structs scoped to just that
function (ties into the scoped-run TODO). Turns version diffing into incremental re-analysis instead
of a one-shot comparison view.

## Dataflow-backed struct suggestion
Once the Joern adapter (see "Surface Joern integration in core") exists, have `ai/suggest-structs`
use cross-function dataflow to find all accesses to a given pointer across the call graph, rather
than inferring structs from access patterns seen in a single function. Should produce far more
complete/accurate struct layouts.

## Type-confidence decay
Distinguish types/names by how they were derived: runtime-observed (e.g. from the debug-time
register-tracking TODO or the Frida bridge) vs. static-only inference (e.g. AI guesses). Surface
that confidence level in the UI so it's clear at a glance what's solid vs. still speculative.

## Auto-generated YARA rules + YARA editor
When the AI enhancer / evidence store identifies a distinctive pattern (custom packer, unusual
crypto constant, anti-debug check), let it draft a YARA rule so the pattern becomes a fast
deterministic detector for future samples — feeds the AI pipeline's findings back into the
deterministic detection layer. Pair this with a proper YARA editor: syntax highlighting, linting,
and inline hints showing which subrules match where and how often in the currently loaded binary
(possibly visualized on a feature/heat map over the binary's address space).

## Entropy/packing overlay in hex editor
Add a per-byte-region entropy heatmap over the hex view (alongside the visualizer side panel idea)
to spot packed/encrypted/compressed sections at a glance — useful for deciding where framework and
library detection should even bother looking.

## Semantic function search via embeddings
Embed decompiled pseudocode (or AI-generated per-function summaries) into a vector index so you can
query the binary semantically — e.g. "find functions that look like a TLS handshake" or "find
something similar to this one" — instead of only being able to grep by name or string.

## Attention heatmap from analyst time
Track how long has actually been spent looking at/editing each function (via BN focus events) and
render it as a heatmap over the call graph or function list. Useful for onboarding onto someone
else's saved `.bndb`, and for spotting "boring" functions that have been skipped but might matter.

## Automatic module/component boundary detection
Cluster the call graph (via the graph-analysis QoL API TODO) to infer likely subsystem boundaries
(e.g. "this cluster of 40 functions is the crypto module") from connectivity alone, then have the AI
enhancer name the cluster instead of only individual functions — gives a map of the binary's
structure before anything has been manually named.

## 1-day/patch-diff assist
Given two versions of a binary (patched vs unpatched) and matched functions from `ux/diff`, have the
AI summarize what changed *semantically* in each modified function (e.g. "added a bounds check
before this write") rather than just showing a raw decompiler diff — speeds up vuln-patch analysis
specifically.

## Auto-generated analyst handoff/break report
Add a command that walks a binary's accumulated evidence (framework detection, named clusters, AI
summaries, YARA matches, applied types/comments) into a single markdown/PDF report — for handing a
sample to someone else, or writing up a bug-bounty/malware report without manually re-collecting
everything already found.

## Fuzzing harness auto-generation
For a function whose signature/argument types have been inferred (manually, via debug-time
tracking, or via suggest-structs), auto-generate a basic libFuzzer/AFL harness stub that calls it
with the right types — shortens the gap between "understood this function" and "can fuzz it."

## Concept for managing plugin/script sprawl (user-facing)
Project is growing into a large number of plugins/scripts across `ai/`, `core/`, `frameworks/`,
`ux/`, `scripts/`. The problem is from the *user's* side, not the codebase's: too many tools to
visually keep track of in BN's menus, and no easy way to answer "what tools do I actually have
available right now, and what do they do?" — a knowledge/discoverability problem, separate from the
registry/manifest idea (which is about registration mechanics, not about surfacing capabilities to
the user). Needs a concept for capability discovery — e.g. a searchable command palette, a
categorized/collapsible menu instead of one flat list, a "what can I run on this binary right now"
contextual suggestion panel driven by what's applicable to the loaded sample, or a cheat-sheet/help
command that lists everything installed with a one-line description. Worth revisiting once the
registry/manifest metadata (if built) exists, since it would double as the data source for this.
