# node-canvas — Interactive graph/canvas view

See `docs/adr/0029-node-canvas-architecture.md` and `CONTEXT.md`
(`node-canvas` glossary) for the design decisions behind this scope.

## Scope
- [x] Custom `QGraphicsView`-based BN view/widget; renders a Qt-free
      `Canvas`/`Node`/`Edge`/`Group` model, doesn't own the model itself
- [x] Add nodes manually (user creates nodes, labels them, positions them)
- [x] Insert nodes from BN views (functions, data items, basic blocks);
      address-bound Node labels resolve live from BN analysis, not frozen
      at insert time
- [x] Unresolved Node handling: address no longer resolves → show raw
      address with a distinguishing prefix symbol; double-click shows a
      toast ("address no longer valid") instead of navigating
- [x] Auto-populate: call-tree from a function, default depth 2, inserted
      into the active Canvas (auto-created with a generated name if none
      is open)
- [x] Auto-populate: xref graph as two separate actions — "add callers"
      and "add callees" — not a single combined direction
- [x] Import external graphs: JSON (native format) and DOT (Graphviz) for
      v1; other formats added later as needed
- [x] Remove nodes individually or in selection
- [x] Group nodes into named, color-coded, collapsible groups; groups may
      nest (a Group can contain other Groups)
- [x] Cascade collapse: collapsing a Group collapses everything nested
      within it; expanding restores each child's own last collapse state
- [x] Collapsed-group edges: external connections reduce to one aggregate
      Edge per connection point at the collapsed box's boundary
- [x] Color coding: set node color, edge color, edge thickness
      programmatically
- [x] Color legend: explicit `(color, label)` registration, independent of
      which elements currently use that color — not auto-derived by
      scanning colors in use
- [x] Save/load canvas layouts, persisted in BN's metadata store (not a
      sidecar file), so a Canvas travels with the `.bndb` it was built from
- [x] Export to image (PNG/PDF): "current" = viewport crop at current
      pan/zoom; "full" = auto-fit whole canvas bounding box; both respect
      on-screen Group collapse state (what you see, not forced expansion)
- [x] Export to Markdown/Mermaid: structural only (nodes, labels, edges),
      Groups mapped to `subgraph` blocks, no color/thickness styling,
      always full canvas (no viewport concept)
- [x] Export to DOT (Graphviz): full round-trip pair with DOT import
- [x] Export to native JSON: full round-trip pair with JSON import, and
      the source of any file re-importable via JSON import
- [x] Auto-layout for freshly-inserted subgraphs (call-tree, xref, import):
      layered/hierarchical via Graphviz `dot` binary if available, naive
      BFS-rank grid fallback if not. Never repositions a node the user has
      already placed; a manual "auto-arrange" command (if added) is an
      explicit opt-in, scoped to a selection
- [x] Navigate: double-click node → jump to address in BN

## API (`api.py`)
- [x] `create_canvas(bv, name) -> Canvas`
- [x] `add_node(canvas, label, address=None, color=None) -> Node`
- [x] `remove_node(canvas, node)`
- [x] `set_node_color(canvas, node, color)`
- [x] `set_edge_color(canvas, edge, color)`
- [x] `set_edge_thickness(canvas, edge, thickness)`
- [x] `add_call_tree(bv, canvas, address, depth=2) -> list[Node]`
- [x] `add_callers(bv, canvas, address, depth=2) -> list[Node]`
- [x] `add_callees(bv, canvas, address, depth=2) -> list[Node]`
- [x] `group_nodes(canvas, nodes, name, color=None, parent=None) -> Group`
- [x] `collapse_group(canvas, group)` / `expand_group(canvas, group)`
- [x] `add_legend_entry(canvas, color, label)`
- [x] `export_image(canvas, path, scope="current"|"full")`
- [x] `export_mermaid(canvas, path)`
- [x] `export_dot(canvas, path)`
- [x] `export_json(canvas, path)`
- [x] `import_dot(canvas, path) -> Canvas`
- [x] `import_json(canvas, path) -> Canvas`
- [x] `api.help()`
- [x] All functions fully type-hinted, no Qt dependency (model is
      scriptable/headless per ADR-0029)

## Notes
- BN has `View` / `DockWidget` APIs for custom views
- Grouping (incl. nesting) is the key differentiator from BN's built-in
  call graph
- Useful for: malware analysis (tracking infection chain), protocol RE
  (message flow), CTF planning
