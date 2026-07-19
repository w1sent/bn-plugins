# diff — Binary diffing and name transfer

See ADR-0030 for the full design rationale behind everything below.

## Scope
- [ ] Diff two binaries (patch-diffing use case first: same binary, one
      version apart) — multi-binary/N-secondary diff, malware-family
      analysis, and firmware-version comparison are deferred extensions
- [ ] Match functions via exact-hash pre-pass + weighted heuristic matching
      on the leftover set (call graph, CFG, constants, string refs)
- [ ] Visual diff view: linked side-by-side disassembly/HLIL for a selected
      function pair; match list/filtering/similarity color via BN's native
      Tag browser (not a custom panel — see ADR-0030/ADR-0024)
- [ ] Apply function names from one binary to another based on matches
- [ ] Apply types/structs from one binary to another based on matches
- [ ] Export/import match results

## Commands
- [ ] "Open Diff View" — opens the diff panel, prompts for binaries to compare
- [ ] "Apply Names from Diff" — transfers matched function names to the current binary
- [ ] "Apply Types from Diff" — transfers matched types/structs to the current binary

## Matching algorithms

### Stage 1: exact-hash pre-pass
- [ ] Hash each function on MLIL SSA form with addresses/constants masked
- [ ] Pair exact hash matches at score 1.0, remove from further consideration
- [ ] `HashBasis` enum on `DiffOptions` (MLIL SSA only for now; enum leaves
      room for HLIL/disassembly-based hashing later)

### Stage 2: weighted heuristic matching (leftover set only)
- [ ] Call graph similarity (function-level: callees, callers)
- [ ] CFG similarity: basic-block hashing (same masked-hash scheme as stage
      1, per block) extended with a 1-hop Weisfeiler-Leman-style signal —
      each block's hash paired with the *unordered set* of successor block
      hashes (unordered, not labeled true/false, to stay robust against
      branch-condition inversion)
  - [ ] Extended-basic-block coarsening before hashing: merge blocks joined
        by an unconditional single-in/single-out edge, to collapse
        compiler-introduced block splits before they enter the hash
  - [ ] Weighted Jaccard scoring (blocks weighted by instruction count),
        not exact-set equality, so residual fragmentation degrades the
        score gracefully
  - [ ] True graph-edit-distance is a future upgrade if block-hashing
        proves too coarse — not part of the initial implementation
- [ ] Constant/string reference similarity: exact-value overlap only (no
      fuzzy/edit-distance matching)
- [ ] Combined weighted score, excluding and renormalizing weights for axes
      that don't apply to a given pair (e.g. leaf functions with no
      callees/strings) rather than scoring them as 0
- [ ] User-configurable weights per algorithm
- [ ] Assignment: optimal bipartite matching (Hungarian) by default on the
      leftover set; optional greedy (highest-score-first) fast mode

## UI
- [ ] Linked side-by-side disassembly/HLIL view for a selected function pair
  - [ ] Attempt reuse of BN's `FlowGraphWidget`/`DisassemblyContainer` for
        the two panes and `SyncGroup` for linked navigation/selection
        (unproven in this codebase — `ViewFrame` construction outside BN's
        own pane management is untested)
  - [ ] Fall back to fully custom Qt rendering (node-canvas-style,
        `QGraphicsView`-based) if `ViewFrame` plumbing is a dead end
  - [ ] Per-block similarity coloring via `FlowGraphNode.highlight` /
        `HighlightStandardColor` (works on synthetic nodes, not just live
        analysis blocks)
- [ ] Match list, filtering (all / matched only / unmatched only / above
      threshold), and similarity color surfaced via BN's native Tag browser
      — no bespoke list/filter panel
- [ ] Click function → jump to address in both binaries

## API (`api.py`)
- [ ] `diff(bv1, bv2, *, weights=None, options: DiffOptions | None = None) -> DiffResult`
- [ ] `get_matches(result, min_score=0.5) -> list[Match]`
- [ ] `apply_names(bv, result, min_score=0.8, overwrite_existing=False) -> int`
      (returns count applied; only overwrites BN-default `sub_*` names
      unless `overwrite_existing=True`)
- [ ] `apply_types(bv, result, min_score=0.8) -> ApplyTypesResult`
      (skips on conflict; distinguishes "already matches" from "differs,
      needs review" rather than one skip count)
- [ ] `api.help()`
- [ ] All functions fully type-hinted
- [ ] Sync by default, `async_run=True` for `Future`-like interface (ADR-0023)
      — no bespoke progress reporting

### Types
- [ ] `DiffResult(matches: list[Match], unmatched_primary: list[Function], unmatched_secondary: list[Function])`
- [ ] `Match(primary_func: Function, secondary_func: Function, score: float, algorithm_scores: dict)`
- [ ] `DiffOptions(hash_basis: HashBasis = HashBasis.MLIL_SSA, assignment: Literal["optimal", "greedy"] = "optimal", weights: dict[str, float] | None = None)`
- [ ] `ApplyTypesResult` distinguishing applied / already-matched / conflict-needs-review counts

## Persistence
- [ ] `DiffResult` persists in BN's metadata store on *both* binaries
      involved in the diff (not a sidecar file — see ADR-0030 for the
      drift-risk rationale, same reasoning as ADR-0029 for node-canvas)

## Settings (BN native)
- [ ] `diff.default_min_score` (float, default `0.8`) — minimum score for auto-apply
- [ ] `diff.weights.call_graph` (float, default `0.3`)
- [ ] `diff.weights.cfg` (float, default `0.3`)
- [ ] `diff.weights.constants` (float, default `0.2`)
- [ ] `diff.weights.strings` (float, default `0.2`)

## Notes
- Similar to BinDiff (zynamics) and Diaphora (Joxean Koret)
- BN already has function hashing and matching primitives — leverage those
- Multi-binary diff: compare primary against N secondaries, show union/intersection
  — deferred until the two-binary patch-diffing core is solid
- Consider: fuzzy hashing for CFG (ssdeep, TLSH) for fast pre-filtering —
  more relevant to the deferred malware-family-analysis extension, where
  exact CFG hashing breaks down, than to patch diffing
- Name transfer is the killer feature — patch diffing, malware family analysis, firmware version comparison
