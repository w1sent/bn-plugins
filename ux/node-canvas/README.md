# Node Canvas — Interactive graph/canvas view

A user-curated, freeform graph workspace: hand-place and group nodes bound
to BN addresses, auto-populate call trees and xref graphs, and
persist/export/import the canvas alongside the binary. See
[docs/adr/0029-node-canvas-architecture.md](../../docs/adr/0029-node-canvas-architecture.md)
and [docs/adr/0034-node-canvas-bulk-edit-dirty-tracking.md](../../docs/adr/0034-node-canvas-bulk-edit-dirty-tracking.md)
for the design decisions behind this plugin, and `CONTEXT.md`'s
`node-canvas` glossary for terminology.

## Opening the panel

Click the Node Canvas icon in Binary Ninja's sidebar (right side by
default). This is a `SidebarWidget`, not a custom view type -- it renders
a Qt-free `Canvas`/`Node`/`Edge`/`Group` model (`model.py`) that doesn't
own the model itself, so the same model can be scripted headlessly via
`api.py`.

A bv can hold multiple canvases at once, shown as tabs above the graph
(plus a trailing **+** tab to create a new one). Click a tab to switch,
middle-click to delete it (with confirmation). Whichever canvas is active
is remembered per-bv and reopened automatically next time the panel is
shown.

## Inserting content

From BN's own views, right-click an address/selection and use:

| Command | Context | Description |
|---|---|---|
| Node Canvas \| Add Function | Address (right-click) | Insert the function at this address |
| Node Canvas \| Add Callers | Address (right-click) | Insert this function and its callers (depth 2) |
| Node Canvas \| Add Callees | Address (right-click) | Insert this function and its callees (depth 2) |
| Node Canvas \| Add Memory Location | Selection (right-click) | Insert the selected address/range, including a hex or decoded-string preview when more than one byte is selected |

These insert into whichever canvas is currently shown in the sidebar
panel -- open the panel first, or the command just logs a reminder to do
so instead of silently picking a canvas.

Within the canvas itself, right-click for a context menu covering node/edge
creation and editing, grouping, relayout, and export/import (see below).

Address-bound node labels resolve live from BN analysis, not frozen at
insert time. If the address no longer resolves (e.g. the function was
removed), the node falls back to showing its raw address with a
distinguishing prefix, and double-clicking it shows a toast instead of
navigating.

## Grouping

Select multiple nodes and use **Group Selected...** to create a named,
color-coded, collapsible group; groups may nest. Collapsing a group
collapses everything nested within it; expanding restores each child's own
last collapse state. A collapsed group's external connections reduce to one
aggregate edge per connection point at the group box's boundary.

## Bulk editing

Selecting more than one node (or more than one edge) and choosing
**Bulk Edit Nodes...** / **Bulk Edit Edges...** only applies the fields you
actually touch in the dialog -- untouched fields are left alone per entity,
even when the selection disagrees on their current value (shown as a
"(mixed)" label/option). See ADR-0034 for why this needed dirty-tracking
rather than a plain value diff.

## Layout

**Relayout (selection or all)...** (or the ⟳ toolbar button) lays out
freshly-inserted or selected nodes using Graphviz's `dot` binary if it's on
`PATH`, falling back to a naive BFS-rank grid otherwise. Layout mode
(Auto/Dot/Grid) is chosen from the expandable toolbar row (▾), which also
holds zoom controls. Manually-placed nodes are never repositioned by
auto-population -- relayout is opt-in and, when triggered with a selection,
scoped to just that selection.

## Export / Import

| Format | Export | Import | Notes |
|---|---|---|---|
| Image (PNG/PDF) | ✓ | -- | "current" = viewport crop at current pan/zoom; "full" = auto-fit whole canvas; both respect on-screen group collapse state |
| Mermaid | ✓ | -- | Structural only (nodes, labels, edges); groups become `subgraph` blocks; no color/thickness styling; always full canvas |
| DOT (Graphviz) | ✓ | ✓ | Full round-trip pair |
| JSON (native) | ✓ | ✓ | Full round-trip pair; the source of any exported JSON file is re-importable |

## Persistence

Canvases are stored in the bv's own metadata store (`bv.store_metadata`),
not a sidecar file, so they travel with the `.bndb` they were built from
(`persistence.py`).

## API (`api.py`)

```python
from ux.node_canvas import api

canvas = api.create_canvas(bv, "my canvas")
api.open_canvas(bv, "my canvas")       # -> Canvas | None
api.list_canvases(bv)                  # -> list[str]
api.save_canvas(bv, canvas)
api.delete_canvas(bv, "my canvas")

node = api.add_node(canvas, "label", address=addr, color="#ff0000")
api.remove_node(canvas, node)
api.set_node_color(canvas, node, "#00ff00")
api.set_node_border_color(canvas, node, "#000000")
api.set_node_label(canvas, node, "new label")

edge = api.add_edge(canvas, src, dst, color=None, thickness=1.0,
                     arrow_start=False, arrow_end=True,
                     style="solid", routing="straight")
api.remove_edge(canvas, edge)
api.set_edge_color(canvas, edge, "#ff0000")
api.set_edge_thickness(canvas, edge, 2.0)
api.set_edge_arrows(canvas, edge, arrow_start=True, arrow_end=True)
api.set_edge_style(canvas, edge, "dashed")     # solid|dashed|dotted|dashdot
api.set_edge_routing(canvas, edge, "orthogonal")
api.reverse_edge(canvas, edge)

api.add_call_tree(bv, canvas, address, depth=2)   # -> list[Node]
api.add_callers(bv, canvas, address, depth=2)     # -> list[Node]
api.add_callees(bv, canvas, address, depth=2)     # -> list[Node]

group = api.group_nodes(canvas, nodes, "name", color=None, parent=None)
api.collapse_group(canvas, group)
api.expand_group(canvas, group)

api.add_legend_entry(canvas, color, label)
api.remove_legend_entry(canvas, index)
api.update_legend_entry(canvas, index, color=None, label=None)
api.move_legend_entry(canvas, index, new_index)

api.export_image(canvas, path, scope="current")  # or "full"
api.export_mermaid(canvas, path)
api.export_dot(canvas, path)
api.export_json(canvas, path)
api.import_dot(canvas, path)   # -> Canvas
api.import_json(canvas, path)  # -> Canvas
```

All functions are fully type-hinted and have no Qt dependency (the model is
scriptable/headless, per ADR-0029). For full API reference, call
`api.help()` in BN's Python console.

## Dependencies

- `core/` (vendored on install)
- Graphviz's `dot` binary, optional -- only used by relayout when present
  on `PATH`; falls back to a grid layout otherwise

## Notes

- Grouping (incl. nesting) is the key differentiator from BN's built-in
  call graph.
- Useful for: malware analysis (tracking infection chain), protocol RE
  (message flow), CTF planning.
