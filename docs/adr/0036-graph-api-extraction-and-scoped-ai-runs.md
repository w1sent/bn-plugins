# Graph-analysis API: extracted from auto-rename's ordering, reused for scoped AI runs

`ai/auto-rename/ordering.py` already implements call-graph traversal
(BFS-based local neighborhoods, leaves-first, top-down, bottom-up, etc.)
duck-typed against a minimal `.start`/`.name`/`.callers`/`.callees`
interface, importing nothing from `binaryninja` and covered by its own
tests. Rather than designing a fresh graph-analysis API from scratch, the
"Graph-analysis QoL API" TODO starts by lifting this logic into
`core/graph.py` verbatim (same duck-typed design, same tests ported over),
with `auto-rename` becoming a consumer of `core.graph` instead of owning
the logic privately. New primitives (reachability, dominators, clustering
for module-boundary detection) get added to `core/graph.py` incrementally,
only when a concrete consumer needs them — not speculatively up front.

This also mostly resolves "Scoped AI tool runs": `rename_functions()`
already accepts `anchor` and `restrict_to`, confining local-* traversal to
an arbitrary function set (e.g. a UI selection) — auto-rename's scoping
support already exists, it just isn't exposed as a one-click command yet.
The actual gap is on the `suggest-structs` side, which only exposes
`suggest_structs(bv, addrs, ...)` (explicit address list) and
`suggest_all(bv, ...)` (whole-binary sweep of `_candidate_vars`); it needs
a neighborhood-scoped candidate finder built on `core.graph`, following
the same shape.

For the "scope to here" UI action (right-click a function → run
auto-rename/suggest-structs on its neighborhood), the default neighborhood
is **direct callees only, 1-hop** — matching the TODO's original wording
and the cheapest/most predictable default cost — with direction (callers
vs. callees) and depth exposed as options on the same dialog for users who
want a wider scope.

Rejected: designing the graph-analysis API independently of
`ordering.py` (would duplicate proven, tested traversal logic that already
does most of what's needed); defaulting the scoped-run neighborhood to
callers+callees at N-hop (broader default cost with no clear win over
opt-in expansion).
