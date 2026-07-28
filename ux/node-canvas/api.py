"""Scriptable, headless node-canvas API -- no Qt/binaryninjaui dependency,
so it works from BN's execute_script (see CONTEXT.md's "Developing and
testing plugins" section) with no widget open. widget.py observes any
Canvas mutated here and re-renders live if a view happens to be open.

    from node_canvas import api
    canvas = api.create_canvas(bv, "malware-chain")
    api.add_callees(bv, canvas, bv.entry_point, depth=2)
    api.export_json(canvas, "/tmp/chain.json")
"""

from __future__ import annotations

import inspect
import sys
from typing import Optional

from .core.logging import get_logger
from . import formats, persistence
from .layout import layout_new_nodes
from .model import DEFAULT_EDGE_ROUTING, DEFAULT_EDGE_STYLE, DEFAULT_EDGE_THICKNESS, Canvas, Edge, Group, Node

logger = get_logger("node_canvas")


# -- canvas lifecycle ---------------------------------------------------


def create_canvas(bv, name: str) -> Canvas:
    canvas = Canvas(name)
    persistence.save_canvas(bv, canvas)
    logger.info("created canvas %r", name)
    return canvas


def open_canvas(bv, name: str) -> Optional[Canvas]:
    return persistence.load_canvas(bv, name)


def list_canvases(bv) -> list[str]:
    return persistence.list_canvas_names(bv)


def save_canvas(bv, canvas: Canvas):
    persistence.save_canvas(bv, canvas)


def delete_canvas(bv, name: str):
    persistence.delete_canvas(bv, name)
    logger.info("deleted canvas %r", name)


# -- nodes/edges ------------------------------------------------------


def add_node(canvas: Canvas, label: str, address: Optional[int] = None, color: Optional[str] = None) -> Node:
    return canvas.add_node(label, address=address, color=color)


def remove_node(canvas: Canvas, node: Node):
    canvas.remove_node(node)


def set_node_color(canvas: Canvas, node: Node, color: str):
    canvas.set_node_color(node, color)


def set_node_border_color(canvas: Canvas, node: Node, border_color: str):
    canvas.set_node_border_color(node, border_color)


def set_node_label(canvas: Canvas, node: Node, label: str):
    canvas.set_node_label(node, label)


def add_edge(canvas: Canvas, src: Node, dst: Node, color: Optional[str] = None, thickness: float = DEFAULT_EDGE_THICKNESS, arrow_start: bool = False, arrow_end: bool = True, style: str = DEFAULT_EDGE_STYLE, routing: str = DEFAULT_EDGE_ROUTING) -> Edge:
    return canvas.add_edge(src, dst, color=color, thickness=thickness, arrow_start=arrow_start, arrow_end=arrow_end, style=style, routing=routing)


def remove_edge(canvas: Canvas, edge: Edge):
    canvas.remove_edge(edge)


def set_edge_color(canvas: Canvas, edge: Edge, color: str):
    canvas.set_edge_color(edge, color)


def set_edge_thickness(canvas: Canvas, edge: Edge, thickness: float):
    canvas.set_edge_thickness(edge, thickness)


def set_edge_arrows(canvas: Canvas, edge: Edge, arrow_start: Optional[bool] = None, arrow_end: Optional[bool] = None):
    canvas.set_edge_arrows(edge, arrow_start=arrow_start, arrow_end=arrow_end)


def set_edge_style(canvas: Canvas, edge: Edge, style: str):
    canvas.set_edge_style(edge, style)


def set_edge_routing(canvas: Canvas, edge: Edge, routing: str):
    canvas.set_edge_routing(edge, routing)


def reverse_edge(canvas: Canvas, edge: Edge):
    canvas.reverse_edge(edge)


# -- auto-populate: call-tree / xref -----------------------------------


def _find_node_by_address(canvas: Canvas, address: int) -> Optional[Node]:
    for node in canvas.nodes.values():
        if node.address == address:
            return node
    return None


def _ensure_node(canvas: Canvas, address: int, label: str, new_nodes: list[Node]) -> Node:
    node = _find_node_by_address(canvas, address)
    if node is None:
        node = canvas.add_node(label, address=address)
        new_nodes.append(node)
    return node


def _find_edge(canvas: Canvas, src: Node, dst: Node) -> Optional[Edge]:
    for edge in canvas.edges.values():
        if edge.src is src and edge.dst is dst:
            return edge
    return None


def _ensure_edge(canvas: Canvas, src: Node, dst: Node) -> Edge:
    """Same-direction (src, dst) pair reuses its existing Edge rather than
    adding a duplicate -- needed both across repeat auto-populate runs (the
    same caller/callee inserted again) and within a single run, since a
    BN Function's `callers`/`callees` lists one entry per call *site*, so a
    function called from three places in the same caller would otherwise
    produce three edges between the same two nodes."""
    edge = _find_edge(canvas, src, dst)
    if edge is None:
        edge = canvas.add_edge(src, dst)
    return edge


def _add_call_tree(bv, canvas: Canvas, address: int, depth: int, direction: str) -> list[Node]:
    functions = bv.get_functions_at(address) or bv.get_functions_containing(address)
    if not functions:
        raise ValueError(f"no function at {address:#x}")
    root_func = functions[0]

    new_nodes: list[Node] = []
    with canvas.batch():
        root_node = _ensure_node(canvas, root_func.start, root_func.name, new_nodes)

        frontier = [(root_func, root_node)]
        seen_addresses = {root_func.start}
        for _ in range(depth):
            next_frontier = []
            for func, node in frontier:
                neighbors = func.callers if direction == "callers" else func.callees
                for neighbor in neighbors:
                    neighbor_node = _ensure_node(canvas, neighbor.start, neighbor.name, new_nodes)
                    if direction == "callers":
                        _ensure_edge(canvas, neighbor_node, node)
                    else:
                        _ensure_edge(canvas, node, neighbor_node)
                    if neighbor.start not in seen_addresses:
                        seen_addresses.add(neighbor.start)
                        next_frontier.append((neighbor, neighbor_node))
            frontier = next_frontier

        if new_nodes:
            layout_new_nodes(canvas, new_nodes)

    persistence.save_canvas(bv, canvas)
    logger.info(
        "canvas %r: add_%s(%#x, depth=%d) inserted %d new node(s)",
        canvas.name, direction, address, depth, len(new_nodes),
    )
    return new_nodes


def add_call_tree(bv, canvas: Canvas, address: int, depth: int = 2) -> list[Node]:
    """The "call tree from a function" auto-populate feature -- callees,
    recursively, to `depth` (per CONTEXT.md's node-canvas scope)."""
    return _add_call_tree(bv, canvas, address, depth, direction="callees")


def add_callers(bv, canvas: Canvas, address: int, depth: int = 2) -> list[Node]:
    return _add_call_tree(bv, canvas, address, depth, direction="callers")


def add_callees(bv, canvas: Canvas, address: int, depth: int = 2) -> list[Node]:
    return _add_call_tree(bv, canvas, address, depth, direction="callees")


# -- groups --------------------------------------------------------------


def group_nodes(canvas: Canvas, nodes: list[Node], name: str, color: Optional[str] = None, parent: Optional[Group] = None) -> Group:
    return canvas.group_nodes(nodes, name, color=color, parent=parent)


def collapse_group(canvas: Canvas, group: Group):
    canvas.collapse_group(group)


def expand_group(canvas: Canvas, group: Group):
    canvas.expand_group(group)


def add_legend_entry(canvas: Canvas, color: str, label: str):
    canvas.add_legend_entry(color, label)


def remove_legend_entry(canvas: Canvas, index: int):
    canvas.remove_legend_entry(index)


def update_legend_entry(canvas: Canvas, index: int, color: Optional[str] = None, label: Optional[str] = None):
    canvas.update_legend_entry(index, color=color, label=label)


def move_legend_entry(canvas: Canvas, index: int, new_index: int):
    canvas.move_legend_entry(index, new_index)


# -- export -------------------------------------------------------------


def export_image(canvas: Canvas, path: str, scope: str = "current"):
    from . import widget

    open_widget = widget.get_widget_for_canvas(canvas)
    if open_widget is None:
        raise RuntimeError(
            "export_image requires an open node-canvas view for this canvas "
            "(image export rasterizes the live Qt scene) -- open one first"
        )
    open_widget.export_image(path, scope=scope)
    logger.info("canvas %r: exported image (%s) to %r", canvas.name, scope, path)


def export_mermaid(canvas: Canvas, path: str):
    formats.export_mermaid(canvas, path)
    logger.info("canvas %r: exported Mermaid to %r", canvas.name, path)


def export_dot(canvas: Canvas, path: str):
    formats.export_dot(canvas, path)
    logger.info("canvas %r: exported DOT to %r", canvas.name, path)


def export_json(canvas: Canvas, path: str):
    formats.export_json(canvas, path)
    logger.info("canvas %r: exported JSON to %r", canvas.name, path)


# -- import (merges into an existing canvas, per CONTEXT.md: "the user or
# script can extend it later on") ---------------------------------------


def _merge_into(dest: Canvas, src: Canvas) -> list[Node]:
    group_map: dict[int, Group] = {}

    def clone_group(group: Group) -> Group:
        if group.id in group_map:
            return group_map[group.id]
        parent = clone_group(group.parent) if group.parent is not None else None
        new_group = dest.group_nodes([], group.name, color=group.color, parent=parent)
        new_group.collapsed = group.collapsed
        group_map[group.id] = new_group
        return new_group

    new_nodes: list[Node] = []
    node_map: dict[int, Node] = {}
    for node in src.nodes.values():
        new_node = dest.add_node(node.label, address=node.address, color=node.color, x=node.x, y=node.y)
        if node.group is not None:
            new_group = clone_group(node.group)
            new_node.group = new_group
            new_group.member_nodes.append(new_node)
        node_map[node.id] = new_node
        new_nodes.append(new_node)

    for edge in src.edges.values():
        dest.add_edge(
            node_map[edge.src.id], node_map[edge.dst.id],
            color=edge.color, thickness=edge.thickness,
            arrow_start=edge.arrow_start, arrow_end=edge.arrow_end, style=edge.style,
        )

    return new_nodes


def import_dot(canvas: Canvas, path: str) -> Canvas:
    """Merges the DOT file's graph into `canvas` (see CONTEXT.md: "the user
    or script can extend it later on"). Note: like add_node/group_nodes/etc.
    above, this doesn't persist by itself -- call save_canvas(bv, canvas)
    if there's no open widget observing (and thus auto-saving) `canvas`."""
    parsed = formats.import_dot(path)
    with canvas.batch():
        new_nodes = _merge_into(canvas, parsed)
        layout_new_nodes(canvas, new_nodes)
    logger.info("canvas %r: imported %d node(s) from DOT %r", canvas.name, len(new_nodes), path)
    return canvas


def import_json(canvas: Canvas, path: str) -> Canvas:
    parsed = formats.import_json(path)
    with canvas.batch():
        new_nodes = _merge_into(canvas, parsed)
        layout_new_nodes(canvas, new_nodes)
    logger.info("canvas %r: imported %d node(s) from JSON %r", canvas.name, len(new_nodes), path)
    return canvas


def help() -> str:
    lines = ["node-canvas api.py -- callable from BN's execute_script:", ""]
    module = sys.modules[__name__]
    for name, obj in sorted(vars(module).items()):
        if name.startswith("_") or not inspect.isfunction(obj) or obj.__module__ != __name__:
            continue
        if name == "help":
            continue
        try:
            sig = inspect.signature(obj)
        except (TypeError, ValueError):
            sig = "(...)"
        lines.append(f"  {name}{sig}")
    return "\n".join(lines)
