"""Qt-free domain model for node-canvas: Canvas/Node/Edge/Group.

No `binaryninjaui`/Qt import anywhere in this module -- see
docs/adr/0029-node-canvas-architecture.md. `widget.py` renders this model
by subscribing as an observer; `api.py` mutates it directly for headless/
scripted use (including BN's execute_script).
"""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional

from .core.logging import get_logger

logger = get_logger("node_canvas")


def _drop_none(d: dict) -> dict:
    """BN's metadata store (see persistence.py) rejects None as a value
    type outright, so to_dict() omits absent optional fields entirely
    rather than storing them as null; from_dict() then uses .get()
    defaults to reconstruct them."""
    return {k: v for k, v in d.items() if v is not None}


def _resolve_address(bv, address):
    """Best-effort live (kind, label) for an address -- kind lets
    widget.py pick a distinct icon per resolution (function/data/symbol,
    see CONTEXT.md's node-canvas glossary); (None, None) if nothing
    resolves (caller then falls back to Unresolved Node display).

    Checked in this order: function, then data var, then generic symbol
    -- a data variable often also has a symbol attached, and should be
    classified as "data", not lumped in with plain "symbol" (imports/
    exports with no function or data var backing them)."""
    func = bv.get_function_at(address)
    if func is not None:
        return "function", func.name

    var = bv.get_data_var_at(address)
    if var is not None:
        return "data", f"data_{address:#x}"

    sym = bv.get_symbol_at(address)
    if sym is not None:
        return "symbol", sym.name

    return None, None


class Node:
    def __init__(self, node_id, label, address=None, color=None, border_color=None, x=0.0, y=0.0):
        self.id = node_id
        self.label = label
        self.address = address
        self.color = color
        self.border_color = border_color
        self.x = x
        self.y = y
        self.group: Optional["Group"] = None

    def display_label(self, bv) -> str:
        """Resolved label with no icon/marker baked in -- that's a
        rendering concern the widget owns (see widget.py's NodeItem),
        so this stays a plain string usable for export formats too."""
        if self.address is None:
            return self.label
        _, label = _resolve_address(bv, self.address)
        if label is None:
            return f"{self.address:#x}"
        return label

    def resolve_kind(self, bv) -> Optional[str]:
        """"function", "data", "symbol", or None (unresolved/no address)
        -- see _resolve_address. Used by widget.py to pick a per-kind
        icon (only a Function gets the "ƒ" marker)."""
        if self.address is None:
            return None
        kind, _ = _resolve_address(bv, self.address)
        return kind

    def is_unresolved(self, bv) -> bool:
        if self.address is None:
            return False
        kind, _ = _resolve_address(bv, self.address)
        return kind is None

    def to_dict(self):
        return _drop_none({
            "id": self.id,
            "label": self.label,
            "address": self.address,
            "color": self.color,
            "border_color": self.border_color,
            "x": self.x,
            "y": self.y,
            "group": self.group.id if self.group else None,
        })


DEFAULT_EDGE_THICKNESS = 3.0
DEFAULT_EDGE_STYLE = "solid"
EDGE_STYLES = ("solid", "dashed", "dotted", "dashdot")


class Edge:
    def __init__(self, edge_id, src: Node, dst: Node, color=None, thickness=DEFAULT_EDGE_THICKNESS, arrow_start=False, arrow_end=True, style=DEFAULT_EDGE_STYLE):
        self.id = edge_id
        self.src = src
        self.dst = dst
        self.color = color
        self.thickness = thickness
        self.arrow_start = arrow_start
        self.arrow_end = arrow_end
        self.style = style

    @property
    def directed(self) -> bool:
        """Whether this edge has an arrow at either end -- used by export
        formats (DOT/Mermaid) that only distinguish "has direction" from
        "plain line", not which end(s)."""
        return self.arrow_start or self.arrow_end

    def to_dict(self):
        return _drop_none({
            "id": self.id,
            "src": self.src.id,
            "dst": self.dst.id,
            "color": self.color,
            "thickness": self.thickness,
            "arrow_start": self.arrow_start,
            "arrow_end": self.arrow_end,
            "style": self.style,
        })


class Group:
    def __init__(self, group_id, name, color=None, parent: Optional["Group"] = None):
        self.id = group_id
        self.name = name
        self.color = color
        self.parent = parent
        self.collapsed = False
        self.child_groups: list["Group"] = []
        self.member_nodes: list[Node] = []

        if parent is not None:
            parent.child_groups.append(self)

    def to_dict(self):
        return _drop_none({
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "parent": self.parent.id if self.parent else None,
            "collapsed": self.collapsed,
        })


@dataclass
class VisibleEdge:
    """One or more underlying Edges collapsed to a single rendered edge
    because one or both endpoints are hidden behind a collapsed Group box."""

    src: object  # Node or Group
    dst: object  # Node or Group
    edges: list = field(default_factory=list)

    @property
    def color(self):
        return self.edges[0].color if self.edges else None

    @property
    def thickness(self):
        return self.edges[0].thickness if self.edges else DEFAULT_EDGE_THICKNESS

    @property
    def count(self):
        return len(self.edges)

    @property
    def arrow_start(self):
        return self.edges[0].arrow_start if self.edges else False

    @property
    def arrow_end(self):
        return self.edges[0].arrow_end if self.edges else True

    @property
    def style(self):
        return self.edges[0].style if self.edges else DEFAULT_EDGE_STYLE


@dataclass
class VisibleGraph:
    nodes: list  # Node, visible individually
    boxes: list  # Group, visible as a collapsed box (hides its members)
    edges: list  # VisibleEdge
    expanded_boundaries: list = field(default_factory=list)  # Group, drawn as an outline around its (still-visible) members


class Canvas:
    def __init__(self, name: str):
        self.name = name
        self.nodes: dict[int, Node] = {}
        self.edges: dict[int, Edge] = {}
        self.groups: dict[int, Group] = {}
        self.legend: list[tuple[str, str]] = []
        self.legend_x: float = 8.0
        self.legend_y: float = 8.0
        self._id_counter = itertools.count(1)
        self._observers: list[Callable[[str], None]] = []
        self._suppress_notify = False
        self._dirty = False

    # -- observation -----------------------------------------------------

    def add_observer(self, callback: Callable[[str], None]):
        self._observers.append(callback)

    def remove_observer(self, callback: Callable[[str], None]):
        if callback in self._observers:
            self._observers.remove(callback)

    def _notify(self, event: str = "change"):
        if self._suppress_notify:
            self._dirty = True
            return
        for callback in list(self._observers):
            callback(event)

    @contextmanager
    def batch(self):
        """Coalesce every _notify() inside the block into a single
        "batch_change" firing at the end -- layout/import/call-tree
        insertion touch many nodes at once, and without this each one
        would trigger a full widget rebuild (see widget.py)."""
        was_suppressed = self._suppress_notify
        self._suppress_notify = True
        try:
            yield
        finally:
            self._suppress_notify = was_suppressed
            if not was_suppressed and self._dirty:
                self._dirty = False
                self._notify("batch_change")

    def _new_id(self) -> int:
        return next(self._id_counter)

    # -- nodes -------------------------------------------------------------

    def add_node(self, label, address=None, color=None, x=0.0, y=0.0) -> Node:
        node = Node(self._new_id(), label, address=address, color=color, x=x, y=y)
        self.nodes[node.id] = node
        logger.debug("canvas %r: added node %r (id=%d, address=%s)", self.name, label, node.id, hex(address) if address is not None else None)
        self._notify("node_added")
        return node

    def remove_node(self, node: Node):
        for edge in [e for e in self.edges.values() if e.src is node or e.dst is node]:
            self.remove_edge(edge)
        if node.group is not None:
            node.group.member_nodes.remove(node)
        del self.nodes[node.id]
        logger.debug("canvas %r: removed node %r (id=%d)", self.name, node.label, node.id)
        self._notify("node_removed")

    def set_node_color(self, node: Node, color):
        node.color = color
        self._notify("node_changed")

    def set_node_border_color(self, node: Node, border_color):
        node.border_color = border_color
        self._notify("node_changed")

    def set_node_label(self, node: Node, label: str):
        node.label = label
        self._notify("node_changed")

    def set_node_position(self, node: Node, x, y):
        node.x = x
        node.y = y
        self._notify("node_moved")

    # -- edges ---------------------------------------------------------

    def add_edge(self, src: Node, dst: Node, color=None, thickness=DEFAULT_EDGE_THICKNESS, arrow_start=False, arrow_end=True, style=DEFAULT_EDGE_STYLE) -> Edge:
        edge = Edge(self._new_id(), src, dst, color=color, thickness=thickness, arrow_start=arrow_start, arrow_end=arrow_end, style=style)
        self.edges[edge.id] = edge
        self._notify("edge_added")
        return edge

    def remove_edge(self, edge: Edge):
        del self.edges[edge.id]
        self._notify("edge_removed")

    def set_edge_color(self, edge: Edge, color):
        edge.color = color
        self._notify("edge_changed")

    def set_edge_thickness(self, edge: Edge, thickness):
        edge.thickness = thickness
        self._notify("edge_changed")

    def set_edge_arrows(self, edge: Edge, arrow_start: Optional[bool] = None, arrow_end: Optional[bool] = None):
        if arrow_start is not None:
            edge.arrow_start = arrow_start
        if arrow_end is not None:
            edge.arrow_end = arrow_end
        self._notify("edge_changed")

    def set_edge_style(self, edge: Edge, style: str):
        edge.style = style
        self._notify("edge_changed")

    def reverse_edge(self, edge: Edge):
        edge.src, edge.dst = edge.dst, edge.src
        edge.arrow_start, edge.arrow_end = edge.arrow_end, edge.arrow_start
        self._notify("edge_changed")

    # -- groups ------------------------------------------------------------

    def group_nodes(self, nodes: list[Node], name: str, color=None, parent: Optional[Group] = None) -> Group:
        group = Group(self._new_id(), name, color=color, parent=parent)
        self.groups[group.id] = group
        for node in nodes:
            if node.group is not None:
                node.group.member_nodes.remove(node)
            node.group = group
            group.member_nodes.append(node)
        logger.debug("canvas %r: grouped %d node(s) into %r (id=%d, parent=%s)", self.name, len(nodes), name, group.id, parent.id if parent else None)
        self._notify("group_added")
        return group

    def remove_group(self, group: Group, keep_members=True):
        for child in list(group.child_groups):
            self.remove_group(child, keep_members=keep_members)
        for node in list(group.member_nodes):
            node.group = group.parent
            if group.parent is not None:
                group.parent.member_nodes.append(node)
        if group.parent is not None:
            group.parent.child_groups.remove(group)
        del self.groups[group.id]
        logger.debug("canvas %r: removed group %r (id=%d), kept its member nodes", self.name, group.name, group.id)
        self._notify("group_removed")

    def add_nodes_to_group(self, nodes: list[Node], group: Group):
        for node in nodes:
            if node.group is group:
                continue
            if node.group is not None:
                node.group.member_nodes.remove(node)
            node.group = group
            group.member_nodes.append(node)
        self._notify("group_changed")

    def remove_nodes_from_group(self, nodes: list[Node]):
        for node in nodes:
            if node.group is None:
                continue
            node.group.member_nodes.remove(node)
            node.group = None
        self._notify("group_changed")

    def set_group_name(self, group: Group, name: str):
        group.name = name
        self._notify("group_changed")

    def set_group_color(self, group: Group, color: Optional[str]):
        group.color = color
        self._notify("group_changed")

    def collapse_group(self, group: Group):
        group.collapsed = True
        self._notify("group_collapsed")

    def expand_group(self, group: Group):
        group.collapsed = False
        self._notify("group_expanded")

    # -- legend --------------------------------------------------------

    def add_legend_entry(self, color: str, label: str):
        self.legend.append((color, label))
        self._notify("legend_changed")

    def remove_legend_entry(self, index: int):
        del self.legend[index]
        self._notify("legend_changed")

    def update_legend_entry(self, index: int, color: Optional[str] = None, label: Optional[str] = None):
        old_color, old_label = self.legend[index]
        self.legend[index] = (color if color is not None else old_color, label if label is not None else old_label)
        self._notify("legend_changed")

    def move_legend_entry(self, index: int, new_index: int):
        entry = self.legend.pop(index)
        self.legend.insert(max(0, min(new_index, len(self.legend))), entry)
        self._notify("legend_changed")

    def set_legend_position(self, x: float, y: float):
        self.legend_x = x
        self.legend_y = y
        self._notify("legend_moved")

    # -- collapse-aware view --------------------------------------------

    def _outermost_collapsed(self, group: Optional[Group]) -> Optional[Group]:
        """Walk the parent chain and return the highest (nearest-root)
        collapsed ancestor -- cascade collapse means any descendant's own
        collapsed flag is moot once an ancestor is collapsed."""
        outer = None
        g = group
        while g is not None:
            if g.collapsed:
                outer = g
            g = g.parent
        return outer

    def _representative(self, element):
        """The thing that should actually be drawn on behalf of `element`:
        itself, or the outermost collapsed Group box hiding it."""
        if isinstance(element, Node):
            outer = self._outermost_collapsed(element.group)
            return outer if outer is not None else element
        if isinstance(element, Group):
            outer = self._outermost_collapsed(element)
            return outer if outer is not None else element
        raise TypeError(element)

    def visible_graph(self) -> VisibleGraph:
        visible_nodes = []
        visible_boxes = {}

        for node in self.nodes.values():
            rep = self._representative(node)
            if rep is node:
                visible_nodes.append(node)
            else:
                visible_boxes[rep.id] = rep

        for group in self.groups.values():
            if group.parent is None:
                rep = self._representative(group)
                if rep is group and group.collapsed:
                    visible_boxes[group.id] = group

        expanded_boundaries = []
        for group in self.groups.values():
            if group.collapsed:
                continue  # already represented as a collapsed box above
            if self._outermost_collapsed(group) is not None:
                continue  # hidden behind a collapsed ancestor's box
            expanded_boundaries.append(group)

        aggregated: dict[tuple, VisibleEdge] = {}
        for edge in self.edges.values():
            src_rep = self._representative(edge.src)
            dst_rep = self._representative(edge.dst)
            if src_rep is dst_rep:
                continue  # internal to a collapsed box, not drawn
            key = (id(src_rep), id(dst_rep))
            if key not in aggregated:
                aggregated[key] = VisibleEdge(src=src_rep, dst=dst_rep, edges=[])
            aggregated[key].edges.append(edge)

        return VisibleGraph(
            nodes=visible_nodes,
            boxes=list(visible_boxes.values()),
            edges=list(aggregated.values()),
            expanded_boundaries=expanded_boundaries,
        )

    # -- serialization (native JSON format) ---------------------------

    def to_dict(self):
        return {
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges.values()],
            "groups": [g.to_dict() for g in self.groups.values()],
            "legend": [{"color": c, "label": l} for c, l in self.legend],
            "legend_x": self.legend_x,
            "legend_y": self.legend_y,
        }

    @classmethod
    def from_dict(cls, data) -> "Canvas":
        canvas = cls(data["name"])

        max_id = 0

        node_by_id = {}
        for n in data.get("nodes", []):
            node = Node(
                n["id"],
                n["label"],
                address=n.get("address"),
                color=n.get("color"),
                border_color=n.get("border_color"),
                x=n.get("x", 0.0),
                y=n.get("y", 0.0),
            )
            canvas.nodes[node.id] = node
            node_by_id[node.id] = node
            max_id = max(max_id, node.id)

        group_by_id = {}
        # groups may reference a parent defined later in the list; two passes
        for g in data.get("groups", []):
            group = Group(g["id"], g["name"], color=g.get("color"), parent=None)
            group.collapsed = g.get("collapsed", False)
            canvas.groups[group.id] = group
            group_by_id[group.id] = group
            max_id = max(max_id, group.id)
        for g in data.get("groups", []):
            parent_id = g.get("parent")
            if parent_id is not None:
                parent = group_by_id[parent_id]
                child = group_by_id[g["id"]]
                child.parent = parent
                parent.child_groups.append(child)
        for n in data.get("nodes", []):
            group_id = n.get("group")
            if group_id is not None:
                node = node_by_id[n["id"]]
                group = group_by_id[group_id]
                node.group = group
                group.member_nodes.append(node)

        for e in data.get("edges", []):
            edge = Edge(
                e["id"],
                node_by_id[e["src"]],
                node_by_id[e["dst"]],
                color=e.get("color"),
                thickness=e.get("thickness", DEFAULT_EDGE_THICKNESS),
                # arrow_end falls back to the old single "directed" field
                # for canvases saved before per-end arrows existed.
                arrow_start=e.get("arrow_start", False),
                arrow_end=e.get("arrow_end", e.get("directed", True)),
                style=e.get("style", DEFAULT_EDGE_STYLE),
            )
            canvas.edges[edge.id] = edge
            max_id = max(max_id, edge.id)

        for entry in data.get("legend", []):
            canvas.legend.append((entry["color"], entry["label"]))
        canvas.legend_x = data.get("legend_x", 8.0)
        canvas.legend_y = data.get("legend_y", 8.0)

        canvas._id_counter = itertools.count(max_id + 1)
        return canvas
