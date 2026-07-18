# node-canvas: Qt-free graph model with dot-assisted layout

`ux/node-canvas` needs a user-curated, hand-positioned graph workspace —
manual node placement, nested/collapsible grouping, and persisted layouts —
none of which BN's built-in `FlowGraph`/`FlowGraphWidget` API supports (it's
built for auto-laid-out, one-graph-per-function control flow, not free
positioning or cross-session persistence). We're building a custom
`QGraphicsView`-based canvas instead.

The domain model (`Canvas`, `Node`, `Edge`, `Group`) is plain Python with no
Qt dependency; the `QGraphicsView` widget is one renderer that observes the
model. This lets `api.py` — including BN's `execute_script`-style automation
— create and modify canvases headlessly with no widget open, and makes
JSON/DOT export a straight serialization of the model rather than a dump of
Qt scene state.

Canvases persist in BN's metadata store, not sidecar files, so a canvas
travels with the `.bndb` it was built from and can't drift out of sync with
the addresses it references.

Freshly-inserted subgraphs (call-tree, xref, import) are placed with a
layered/hierarchical layout via Graphviz's `dot` binary when available,
falling back to a naive BFS-rank grid otherwise — layout never repositions
a node the user has already placed by hand. We chose to shell out to `dot`
rather than write a layout engine because DOT is already a first-class
import/export format for the plugin, so the dependency is already justified.

**Considered and rejected:**
- Reusing BN's `FlowGraph` — no free positioning, no persistence.
- Force-directed layout for all insertions — a second layout algorithm to
  build/maintain for import graphs, a lower-priority case than call-tree/xref.
- Sidecar JSON files for persistence — can drift from the `.bndb`, adds file
  management the metadata store gives for free.
