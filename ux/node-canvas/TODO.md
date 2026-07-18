# node-canvas — Interactive graph/canvas view

See `docs/adr/0029-node-canvas-architecture.md` and `CONTEXT.md`
(`node-canvas` glossary) for the design decisions behind this scope.

## Scope
- [ ] Custom `QGraphicsView`-based BN view/widget; renders a Qt-free
      `Canvas`/`Node`/`Edge`/`Group` model, doesn't own the model itself
- [ ] Add nodes manually (user creates nodes, labels them, positions them)
- [ ] Insert nodes from BN views (functions, data items, basic blocks);
      address-bound Node labels resolve live from BN analysis, not frozen
      at insert time
- [ ] Unresolved Node handling: address no longer resolves → show raw
      address with a distinguishing prefix symbol; double-click shows a
      toast ("address no longer valid") instead of navigating
- [ ] Auto-populate: call-tree from a function, default depth 2, inserted
      into the active Canvas (auto-created with a generated name if none
      is open)
- [ ] Auto-populate: xref graph as two separate actions — "add callers"
      and "add callees" — not a single combined direction
- [ ] Import external graphs: JSON (native format) and DOT (Graphviz) for
      v1; other formats added later as needed
- [ ] Remove nodes individually or in selection
- [ ] Group nodes into named, color-coded, collapsible groups; groups may
      nest (a Group can contain other Groups)
- [ ] Cascade collapse: collapsing a Group collapses everything nested
      within it; expanding restores each child's own last collapse state
- [ ] Collapsed-group edges: external connections reduce to one aggregate
      Edge per connection point at the collapsed box's boundary
- [ ] Color coding: set node color, edge color, edge thickness
      programmatically
- [ ] Color legend: explicit `(color, label)` registration, independent of
      which elements currently use that color — not auto-derived by
      scanning colors in use
- [ ] Save/load canvas layouts, persisted in BN's metadata store (not a
      sidecar file), so a Canvas travels with the `.bndb` it was built from
- [ ] Export to image (PNG/PDF): "current" = viewport crop at current
      pan/zoom; "full" = auto-fit whole canvas bounding box; both respect
      on-screen Group collapse state (what you see, not forced expansion)
- [ ] Export to Markdown/Mermaid: structural only (nodes, labels, edges),
      Groups mapped to `subgraph` blocks, no color/thickness styling,
      always full canvas (no viewport concept)
- [ ] Export to DOT (Graphviz): full round-trip pair with DOT import
- [ ] Export to native JSON: full round-trip pair with JSON import, and
      the source of any file re-importable via JSON import
- [ ] Auto-layout for freshly-inserted subgraphs (call-tree, xref, import):
      layered/hierarchical via Graphviz `dot` binary if available, naive
      BFS-rank grid fallback if not. Never repositions a node the user has
      already placed; a manual "auto-arrange" command (if added) is an
      explicit opt-in, scoped to a selection
- [ ] Navigate: double-click node → jump to address in BN

## API (`api.py`)
- [ ] `create_canvas(bv, name) -> Canvas`
- [ ] `add_node(canvas, label, address=None, color=None) -> Node`
- [ ] `remove_node(canvas, node)`
- [ ] `set_node_color(canvas, node, color)`
- [ ] `set_edge_color(canvas, edge, color)`
- [ ] `set_edge_thickness(canvas, edge, thickness)`
- [ ] `add_call_tree(canvas, func, depth=2) -> list[Node]`
- [ ] `add_callers(canvas, address, depth=2) -> list[Node]`
- [ ] `add_callees(canvas, address, depth=2) -> list[Node]`
- [ ] `group_nodes(canvas, nodes, name, color=None, parent=None) -> Group`
- [ ] `collapse_group(canvas, group)` / `expand_group(canvas, group)`
- [ ] `add_legend_entry(canvas, color, label)`
- [ ] `export_image(canvas, path, scope="current"|"full")`
- [ ] `export_mermaid(canvas, path)`
- [ ] `export_dot(canvas, path)`
- [ ] `export_json(canvas, path)`
- [ ] `import_dot(canvas, path) -> Canvas`
- [ ] `import_json(canvas, path) -> Canvas`
- [ ] `api.help()`
- [ ] All functions fully type-hinted, no Qt dependency (model is
      scriptable/headless per ADR-0029)

## Notes
- BN has `View` / `DockWidget` APIs for custom views
- Grouping (incl. nesting) is the key differentiator from BN's built-in
  call graph
- Useful for: malware analysis (tracking infection chain), protocol RE
  (message flow), CTF planning
