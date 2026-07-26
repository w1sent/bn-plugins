"""Auto-layout for freshly-inserted subgraphs (call-tree/xref/import), per
docs/adr/0029-node-canvas-architecture.md: layered/hierarchical via
Graphviz's `dot` binary when available, naive BFS-rank grid fallback
otherwise. Never repositions a node the caller didn't include in
`new_nodes` -- existing user-placed nodes are left alone.
"""

from __future__ import annotations

import shutil
import subprocess
from collections import defaultdict, deque

from .core.logging import get_logger
from .model import Canvas, Node

logger = get_logger("node_canvas")

_DOT_SCALE = 100.0  # dot positions are in inches; scale up to pixel-ish units

# Canonical node box size and layout padding -- widget.py imports these
# rather than keeping its own copy, so the renderer and the layout engine
# never disagree about how much space a node needs.
NODE_WIDTH = 140.0
NODE_HEIGHT = 40.0
_PADDING = 40.0  # minimum gap between adjacent node edges, in both engines

_RANK_SPACING = NODE_HEIGHT + _PADDING * 2

# Headless (no Qt) estimate of a node's rendered width, used to size layout
# spacing here and, via widget.py's import of this same function, group
# boundary boxes -- before any real font metrics are available (widget.py
# is the only module allowed to import Qt, per docs/adr/0029). Errs
# generous: the real QFontMetrics measurement in widget.py's NodeItem is
# the source of truth for what actually gets drawn, this only needs to
# reserve *enough* room that layout doesn't pack nodes closer than the
# real boxes will be.
_CHAR_WIDTH_ESTIMATE = 7.5
_LABEL_PADDING = 36.0


def estimate_node_width(label: str) -> float:
    return max(NODE_WIDTH, len(label) * _CHAR_WIDTH_ESTIMATE + _LABEL_PADDING)


def _existing_bbox(canvas: Canvas, exclude: set[int]):
    xs = [n.x for n in canvas.nodes.values() if n.id not in exclude]
    ys = [n.y for n in canvas.nodes.values() if n.id not in exclude]
    if not xs:
        return None
    max_x = max(n.x + estimate_node_width(n.label) for n in canvas.nodes.values() if n.id not in exclude)
    return min(xs), min(ys), max_x, max(ys)


def _dot_available() -> bool:
    return shutil.which("dot") is not None


def _layout_with_dot(new_nodes: list[Node], internal_edges) -> dict[int, tuple[float, float]]:
    # Without explicit width/height, dot assumes its own small default node
    # size and packs nodes far closer than the boxes widget.py actually
    # renders, so positions from an unmodified dot layout overlap once
    # drawn. fixedsize=true makes dot honor these exactly instead of
    # treating them as minimums; nodesep/ranksep add the same padding grid
    # layout uses. Each node gets its own estimated width (see
    # estimate_node_width) rather than a shared constant, so long labels
    # get their own extra breathing room instead of overlapping neighbors.
    widths = {n.id: estimate_node_width(n.label) for n in new_nodes}
    node_h_in = NODE_HEIGHT / _DOT_SCALE
    nodesep_in = _PADDING / _DOT_SCALE
    ranksep_in = (_PADDING * 2) / _DOT_SCALE

    lines = ["digraph G {", f"  nodesep={nodesep_in};", f"  ranksep={ranksep_in};"]
    for node in new_nodes:
        node_w_in = widths[node.id] / _DOT_SCALE
        lines.append(f'  n{node.id} [label="", shape=box, fixedsize=true, width={node_w_in}, height={node_h_in}];')
    for src, dst in internal_edges:
        lines.append(f"  n{src.id} -> n{dst.id};")
    lines.append("}")
    dot_src = "\n".join(lines)

    result = subprocess.run(
        ["dot", "-Tplain"],
        input=dot_src,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"dot failed: {result.stderr}")

    positions = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts or parts[0] != "node":
            continue
        # node <name> <x> <y> <width> <height> ... -- x/y are the node's
        # CENTER in dot's plain output, but positions here are consumed as
        # a top-left corner (see widget.py's NodeItem: setPos == top-left
        # of its (0, 0, width, height) rect), so re-center on conversion,
        # using this node's own width rather than a shared constant.
        name, x, y = parts[1], float(parts[2]), float(parts[3])
        node_id = int(name[1:])
        positions[node_id] = (x * _DOT_SCALE - widths[node_id] / 2, y * _DOT_SCALE - NODE_HEIGHT / 2)
    return positions


def _layout_with_bfs_grid(new_nodes: list[Node], internal_edges) -> dict[int, tuple[float, float]]:
    adjacency = defaultdict(set)
    for src, dst in internal_edges:
        adjacency[src.id].add(dst.id)
        adjacency[dst.id].add(src.id)

    rank_of: dict[int, int] = {}
    remaining = {n.id for n in new_nodes}

    while remaining:
        root = min(remaining)  # deterministic
        queue = deque([(root, 0)])
        rank_of[root] = 0
        remaining.discard(root)
        while queue:
            node_id, rank = queue.popleft()
            for neighbor in adjacency[node_id]:
                if neighbor in remaining:
                    remaining.discard(neighbor)
                    rank_of[neighbor] = rank + 1
                    queue.append((neighbor, rank + 1))

    by_rank = defaultdict(list)
    for node_id, rank in rank_of.items():
        by_rank[rank].append(node_id)

    widths = {n.id: estimate_node_width(n.label) for n in new_nodes}

    positions = {}
    for rank, node_ids in by_rank.items():
        x = 0.0
        for node_id in sorted(node_ids):
            positions[node_id] = (x, rank * _RANK_SPACING)
            x += widths[node_id] + _PADDING
    return positions


def layout_new_nodes(canvas: Canvas, new_nodes: list[Node], mode: str = "auto"):
    """Position `new_nodes` (already added to `canvas`) using a layered
    layout, then translate the whole cluster to sit clear of whatever
    other nodes are NOT in `new_nodes`. Nodes outside `new_nodes` are
    never touched -- so passing the full node set (a "relayout everything"
    request) lays out from scratch, and passing a selection subset
    relayouts just that subset clear of the rest.

    `mode`: "auto" (dot if available, else grid fallback), "dot" (force,
    raises if the `dot` binary isn't available), or "grid" (force)."""
    if not new_nodes:
        return

    new_ids = {n.id for n in new_nodes}
    internal_edges = [
        (e.src, e.dst)
        for e in canvas.edges.values()
        if e.src.id in new_ids and e.dst.id in new_ids
    ]

    if mode == "grid":
        positions = _layout_with_bfs_grid(new_nodes, internal_edges)
    elif mode == "dot":
        positions = _layout_with_dot(new_nodes, internal_edges)
    elif _dot_available():
        try:
            positions = _layout_with_dot(new_nodes, internal_edges)
        except Exception as exc:
            logger.warning("dot layout failed (%s), falling back to grid", exc)
            positions = _layout_with_bfs_grid(new_nodes, internal_edges)
    else:
        positions = _layout_with_bfs_grid(new_nodes, internal_edges)

    for node in new_nodes:
        if node.id not in positions:
            positions[node.id] = (0.0, 0.0)

    min_x = min(x for x, _ in positions.values())
    min_y = min(y for _, y in positions.values())

    bbox = _existing_bbox(canvas, exclude=new_ids)
    if bbox is None:
        offset_x, offset_y = 0.0, 0.0
    else:
        # max_x from _existing_bbox is already a right edge (node.x + its
        # estimated rendered width), so the buffer here only needs to be a
        # clearance gap, not another full column width on top of that.
        _, _, max_x, _ = bbox
        offset_x = max_x + _PADDING * 2 - min_x
        offset_y = -min_y

    logger.debug("canvas %r: laying out %d node(s), mode=%s", canvas.name, len(new_nodes), mode)
    with canvas.batch():
        for node in new_nodes:
            x, y = positions[node.id]
            canvas.set_node_position(node, x + offset_x, y + offset_y)
