# diff: exact-hash pre-pass + WL-style CFG scoring, BN-widget-reuse UI

**Status: superseded, 2026-08-02.** `ux/diff` was removed (never got past
the design/`TODO.md` stage — no code existed) because Binary Ninja 6.0 is
planned to ship its own native diffing tool, making a custom-built one
redundant. Left in place as a record of the matching-pipeline design work
in case a future gap between BN's native tool and this repo's needs (e.g.
tighter integration with `core`'s evidence store, or the AI plugins) makes
some of this reasoning worth revisiting.

`ux/diff` is scoped to patch diffing first (same binary, one version apart) —
not malware-family clustering or cross-toolchain firmware comparison. Those
have very different similarity characteristics (heavier reliance on fuzzy
hashing, lower baseline similarity) and are deferred as later extensions once
the patch-diffing core works.

## Matching pipeline

Matching runs in two stages:

1. **Exact-hash pre-pass.** Every function is hashed on its MLIL SSA form
   with addresses and constants masked, so a rebase/relink doesn't break a
   match that's otherwise identical. Exact hash matches are paired at score
   1.0 and removed from further consideration — in patch diffing the large
   majority of functions are unchanged, so this pass does most of the work
   cheaply and leaves only genuinely-changed functions for the expensive
   stage. The hash basis is a `HashBasis` enum on `DiffOptions` (not a
   strategy interface) — MLIL SSA is the only basis implemented now, but the
   enum leaves room to add HLIL- or disassembly-based hashing later without
   committing to a plugin-style extension contract nobody's asked for yet.

2. **Weighted heuristic matching on the leftover set**, combining:
   - call graph similarity (callers/callees)
   - CFG similarity: basic-block hashing (same MLIL-SSA masked hash as the
     exact pass, computed per-block) extended with a 1-hop
     Weisfeiler-Leman-style signal — each block's hash is compared not just
     as a bag, but alongside the *unordered set* of its successor block
     hashes, so adjacency (not just block content) contributes to the score.
     Unordered rather than labeled (true/false) successor sets, because
     labeled edges break on the common compiler behavior of inverting a
     branch condition, which is semantically meaningless churn.
   - constant/string reference similarity: exact-value overlap only (no
     fuzzy/edit-distance matching — the low weight this signal carries in
     patch diffing doesn't justify the added pairwise cost)
   - combined via a user-configurable weighted score (`DiffOptions.weights`,
     BN Settings defaults per `diff.weights.*`)

   Basic-block hashing is deliberately chosen over full graph-edit-distance:
   GED is NP-hard and needs an approximation to stay tractable, which is
   more implementation complexity than a first pass over the *second*-most
   important signal (after call graph) justifies. True GED (or deeper WL
   iterations, which the 1-hop scheme above generalizes toward) is a
   candidate future upgrade if block-hashing proves too coarse in practice.

   Two mitigations counter block-hashing's main weakness — spurious block
   splits from compiler/optimizer churn breaking otherwise-identical
   functions:
   - **Extended-basic-block coarsening**: before hashing, merge any block
     pair joined by an unconditional edge where the predecessor has exactly
     one successor and the successor has exactly one predecessor. This
     collapses most compiler-introduced block splits (instruction
     scheduling, jump-threading) back to one node before they ever enter the
     hash.
   - **Weighted Jaccard scoring** (blocks weighted by instruction count)
     instead of exact-set equality, so residual fragmentation the EBB pass
     doesn't catch degrades the score proportionally instead of an
     all-or-nothing miss.

   When a signal doesn't apply to a given pair (e.g. a leaf function has no
   callees, or no string/constant refs), that axis is excluded and the
   remaining weights renormalized — not scored as 0 — so small self-contained
   functions aren't systematically penalized for having nothing to compare
   on an axis that structurally doesn't apply to them.

3. **Assignment**: optimal bipartite matching (Hungarian algorithm) by
   default on the leftover set — affordable specifically because the
   exact-hash pre-pass already strips out the bulk of functions, leaving a
   residual set small enough for cubic-cost optimal assignment to be
   worthwhile where ambiguity is actually concentrated. An optional greedy
   (highest-score-first) fast mode is available for large residual sets.

## Write-back semantics

- `apply_names` only overwrites functions still at BN's default name
  (`sub_*`-style); an explicit `overwrite_existing: bool = False` option
  opts into clobbering user-set names. Protects prior manual naming work by
  default — a match above threshold is still a wrong-name risk, and
  shouldn't silently override work the user already did.
- `apply_types` skips on conflict (a same-named type with a different
  definition) rather than overwriting — struct layout differences propagate
  to every function that references the type via HLIL, so an overwrite can
  silently corrupt unrelated analysis in ways much harder to notice than a
  wrong function name. The result/log distinguishes "already matches,
  nothing to do" from "differs, needs manual review" rather than collapsing
  both into one skip count.

## UI

Per ADR-0024 (prefer BN-native display over custom UI), the diff view is
scoped to only the piece BN's native views genuinely can't do: a linked
side-by-side disassembly/HLIL comparison for one selected function pair.
Match list, filtering, and score display ride on tags + BN's native Tag
browser (per ADR-0025's tagging convention) rather than a bespoke list
panel.

For the side-by-side pane itself, the plan is to attempt reusing BN's own
`FlowGraphWidget`/`DisassemblyContainer` (both public, embeddable `QWidget`s)
for the two panes, `SyncGroup` for linked navigation/selection between them,
and `FlowGraphNode.highlight`/`HighlightStandardColor` for per-block
similarity coloring — the highlight API works on synthetic nodes in a
standalone `FlowGraph`, not just live analysis blocks, so a diff-specific
graph of changed blocks can be colored without custom paint code.

This is unproven in this codebase — no existing plugin (including
node-canvas) reuses these BN view classes, and `DisassemblyContainer`/
`LinearView` require a `ViewFrame*` that BN normally supplies via its own
pane management, not something trivially constructed standalone. If that
plumbing turns out to be a dead end, the fallback is fully custom Qt
rendering, following node-canvas's precedent (ADR-0029) for building a
custom `QGraphicsView`-based widget when BN's built-in views don't fit.

## Persistence

`DiffResult` persists in BN's metadata store on *both* binaries involved in
the diff (not a sidecar file), following ADR-0029's precedent: a
`DiffResult` references addresses in two binaries, and either side going
stale (reanalysis, renaming, address shifts) would silently desync a sidecar
file with no way to detect it. Metadata-store persistence ties the result's
lifetime to the `.bndb`s it was computed from, on both sides.

## Sync/async

Standard ADR-0023 convention applies as-is: `diff()` is synchronous by
default, `async_run=True` for the `Future`-like interface, no bespoke
progress-reporting mechanism. If `diff()` proves slow enough in practice to
need phase-level progress reporting, that's a reason to extend the
convention repo-wide later — not to build a one-off mechanism for this
plugin now.

**Considered and rejected:**
- Uniform "run all four algorithms on every pair" instead of an exact-hash
  pre-pass — wastes the dominant patch-diffing case (unchanged functions)
  on expensive weighted comparison.
- True graph-edit-distance for CFG similarity now — NP-hard, needs an
  approximation, more complexity than the second-priority signal justifies
  in a patch-diffing-first design. Deferred as a future upgrade.
- Labeled (true/false) successor edges for CFG hashing — breaks on branch
  condition inversion, a common and semantically meaningless compiler
  transformation.
- Fuzzy/edit-distance string matching — adds pairwise string-distance cost
  for a signal that's both lowest-weighted and lowest-priority for the
  patch-diffing use case.
- Greedy-only assignment — the exact-hash pre-pass makes the residual set
  small enough that optimal (Hungarian) assignment is affordable, and that's
  exactly where assignment ambiguity concentrates.
- Unconditional overwrite in `apply_names`/`apply_types` — too easy to
  clobber prior user work or corrupt unrelated analysis via type layout
  changes; both default to non-destructive behavior with explicit opt-in.
- A full custom match-list/filter panel (as originally scoped in the TODO)
  — BN's Tag browser already covers list/filter/color once matches are
  tagged, so only the two-binary-linked disassembly view needs custom work.
- Sidecar file for `DiffResult` persistence — same drift risk ADR-0029
  already rejected for node-canvas, now doubled since two binaries are
  involved instead of one.
