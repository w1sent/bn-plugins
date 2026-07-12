# node-canvas — Interactive graph/canvas view

## Scope
- [ ] Custom BN view/widget for interactive node-based graph
- [ ] Add nodes manually (user creates nodes, labels them, positions them)
- [ ] Insert nodes from BN views (functions, data items, basic blocks)
- [ ] Auto-populate: call-tree, import graph, cross-reference graph
- [ ] Remove nodes individually or in selection
- [ ] Group nodes into named groups (collapsible, color-coded)
- [ ] Color coding: set node color, edge color, edge thickness programmatically
- [ ] Color legend: display a legend for color meanings
- [ ] Save/load canvas layouts
- [ ] Navigate: double-click node → jump to address in BN

## API (`api.py`)
- [ ] `create_canvas(bv, name) -> Canvas`
- [ ] `add_node(canvas, label, address=None, color=None) -> Node`
- [ ] `set_node_color(canvas, node, color)`
- [ ] `set_edge_color(canvas, edge, color)`
- [ ] `set_edge_thickness(canvas, edge, thickness)`
- [ ] `add_call_tree(canvas, func) -> list[Node]`
- [ ] `remove_node(canvas, node)`
- [ ] `group_nodes(canvas, nodes, name, color=None) -> Group`
- [ ] `api.help()`
- [ ] All functions fully type-hinted

## Notes
- BN has `View` / `DockWidget` APIs for custom views
- Graph layout: consider reusing BN's graph rendering or a custom canvas
- Grouping is the key differentiator from BN's built-in call graph
- Useful for: malware analysis (tracking infection chain), protocol RE (message flow), CTF planning
