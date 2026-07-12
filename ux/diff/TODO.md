# diff — Binary diffing and name transfer

## Scope
- [ ] Diff two or more binaries side-by-side
- [ ] Match functions by similarity (call graph, control flow, constants, string refs)
- [ ] Visual diff view: matched/unmatched functions, similarity scores, side-by-side comparison
- [ ] Apply function names from one binary to another based on matches
- [ ] Apply types/structs from one binary to another
- [ ] Export/import match results

## Commands
- [ ] "Open Diff View" — opens the diff panel, prompts for binaries to compare
- [ ] "Apply Names from Diff" — transfers matched function names to the current binary
- [ ] "Apply Types from Diff" — transfers matched types/structs to the current binary

## Matching algorithms
- [ ] Call graph similarity (function-level: callees, callers)
- [ ] Control flow graph similarity (basic block hashing, graph edit distance)
- [ ] Constant/string reference similarity
- [ ] Combined weighted score
- [ ] User-configurable weights per algorithm

## UI
- [ ] Side-by-side or stacked function list (matched/unmatched)
- [ ] Color-coded similarity: green (high), yellow (medium), red (low)
- [ ] Click function → jump to address in both binaries
- [ ] Side-by-side disassembly/HLIL diff for selected function pair
- [ ] Filter: show all / matched only / unmatched only / above threshold

## API (`api.py`)
- [ ] `diff(bv1, bv2, *, weights=None) -> DiffResult`
- [ ] `get_matches(result, min_score=0.5) -> list[Match]`
- [ ] `apply_names(bv, result, min_score=0.8) -> int`  (returns count applied)
- [ ] `apply_types(bv, result, min_score=0.8) -> int`
- [ ] `api.help()`
- [ ] All functions fully type-hinted

### Types
- [ ] `DiffResult(matches: list[Match], unmatched_primary: list[Function], unmatched_secondary: list[Function])`
- [ ] `Match(primary_func: Function, secondary_func: Function, score: float, algorithm_scores: dict)`

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
- Consider: fuzzy hashing for CFG (ssdeep, TLSH) for fast pre-filtering
- Name transfer is the killer feature — patch diffing, malware family analysis, firmware version comparison
