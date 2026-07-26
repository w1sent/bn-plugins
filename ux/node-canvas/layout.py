"""Auto-layout for freshly-inserted subgraphs (call-tree/xref/import), per
docs/adr/0029-node-canvas-architecture.md: layered/hierarchical via
Graphviz's `dot` binary when available, naive BFS-rank grid fallback
otherwise. Never repositions a node the caller didn't include in
`new_nodes` -- existing user-placed nodes are left alone.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from collections import defaultdict, deque
from typing import Callable, Optional

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

# Cap on a node's width before its label wraps onto more lines instead of
# growing wider -- long names shouldn't force scrolling far horizontally to
# see one whole node.
NODE_MAX_WIDTH = 260.0

# Headless (no Qt) estimate of a node's rendered (width, height), used to
# size layout spacing here and, via widget.py's import of these same
# functions, group boundary boxes -- before any real font metrics are
# available (widget.py is the only module allowed to import Qt, per
# docs/adr/0029). Errs generous: the real QFontMetrics measurement (and
# actual wrapping) in widget.py's NodeItem is the source of truth for what
# actually gets drawn, this only needs to reserve *enough* room in both
# dimensions that layout doesn't pack nodes closer than the real boxes will
# be -- including a multi-line custom node's own explicit "\n" breaks.
_CHAR_WIDTH_ESTIMATE = 7.5
_LABEL_PADDING = 36.0
_LINE_HEIGHT_ESTIMATE = 19.0
_LABEL_VMARGIN = NODE_HEIGHT - _LINE_HEIGHT_ESTIMATE


def _estimate_paragraph_lines(paragraph: str, max_content_width: float) -> int:
    raw_width = len(paragraph) * _CHAR_WIDTH_ESTIMATE
    if raw_width <= max_content_width or max_content_width <= 0:
        return 1
    return math.ceil(raw_width / max_content_width)


def estimate_node_size(label: str) -> tuple[float, float]:
    max_content_width = NODE_MAX_WIDTH - _LABEL_PADDING
    paragraphs = label.split("\n")
    total_lines = sum(_estimate_paragraph_lines(p, max_content_width) for p in paragraphs) or 1
    widest_paragraph = max((len(p) * _CHAR_WIDTH_ESTIMATE for p in paragraphs), default=0.0)

    width = max(NODE_WIDTH, min(widest_paragraph, max_content_width) + _LABEL_PADDING)
    height = max(NODE_HEIGHT, total_lines * _LINE_HEIGHT_ESTIMATE + _LABEL_VMARGIN)
    return width, height


def estimate_node_width(label: str) -> float:
    return estimate_node_size(label)[0]


def estimate_node_height(label: str) -> float:
    return estimate_node_size(label)[1]


# A node's size for layout purposes: (width, height). Defaults to the
# headless label-based estimate above -- the only option when nothing has
# been rendered yet (a brand-new node, or any headless/execute_script use
# per docs/adr/0029). widget.py's relayout, though, passes a lookup that
# prefers each node's *actual* current rendered box (its label may have
# been resolved/renamed/re-wrapped since insertion, so the stored
# Node.label this estimate is based on can be stale) -- see
# CanvasWidget._node_render_width/_node_render_height.
SizeFn = Callable[[Node], tuple[float, float]]


def _default_size(node: Node) -> tuple[float, float]:
    return estimate_node_size(node.label)


def _existing_bbox(canvas: Canvas, exclude: set[int], size_of: SizeFn):
    xs = [n.x for n in canvas.nodes.values() if n.id not in exclude]
    ys = [n.y for n in canvas.nodes.values() if n.id not in exclude]
    if not xs:
        return None
    max_x = max(n.x + size_of(n)[0] for n in canvas.nodes.values() if n.id not in exclude)
    return min(xs), min(ys), max_x, max(ys)


def _dot_available() -> bool:
    return shutil.which("dot") is not None


def _layout_with_dot(new_nodes: list[Node], internal_edges, size_of: SizeFn) -> dict[int, tuple[float, float]]:
    # Without explicit width/height, dot assumes its own small default node
    # size and packs nodes far closer than the boxes widget.py actually
    # renders, so positions from an unmodified dot layout overlap once
    # drawn. fixedsize=true makes dot honor these exactly instead of
    # treating them as minimums; nodesep/ranksep add the same padding grid
    # layout uses. Each node gets its own (width, height) from `size_of`
    # rather than shared constants, so long/wrapped or multi-line labels
    # get their own extra breathing room -- in both dimensions -- instead
    # of overlapping neighbors.
    sizes = {n.id: size_of(n) for n in new_nodes}
    nodesep_in = _PADDING / _DOT_SCALE
    ranksep_in = (_PADDING * 2) / _DOT_SCALE

    lines = ["digraph G {", f"  nodesep={nodesep_in};", f"  ranksep={ranksep_in};"]
    for node in new_nodes:
        w, h = sizes[node.id]
        node_w_in = w / _DOT_SCALE
        node_h_in = h / _DOT_SCALE
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
        # using this node's own width/height rather than shared constants.
        name, x, y = parts[1], float(parts[2]), float(parts[3])
        node_id = int(name[1:])
        w, h = sizes[node_id]
        positions[node_id] = (x * _DOT_SCALE - w / 2, y * _DOT_SCALE - h / 2)
    return positions


def _layout_with_bfs_grid(new_nodes: list[Node], internal_edges, size_of: SizeFn) -> dict[int, tuple[float, float]]:
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

    sizes = {n.id: size_of(n) for n in new_nodes}

    positions = {}
    y = 0.0
    for rank in sorted(by_rank):
        x = 0.0
        row_height = NODE_HEIGHT
        for node_id in sorted(by_rank[rank]):
            w, h = sizes[node_id]
            positions[node_id] = (x, y)
            x += w + _PADDING
            row_height = max(row_height, h)
        y += row_height + _PADDING * 2
    return positions


def layout_new_nodes(
    canvas: Canvas, new_nodes: list[Node], mode: str = "auto", size_of: Optional[SizeFn] = None,
):
    """Position `new_nodes` (already added to `canvas`) using a layered
    layout, then translate the whole cluster to sit clear of whatever
    other nodes are NOT in `new_nodes`. Nodes outside `new_nodes` are
    never touched -- so passing the full node set (a "relayout everything"
    request) lays out from scratch, and passing a selection subset
    relayouts just that subset clear of the rest.

    `mode`: "auto" (dot if available, else grid fallback), "dot" (force,
    raises if the `dot` binary isn't available), or "grid" (force).

    `size_of`: per-node (width, height), defaulting to the headless
    label-based estimate. Callers that already have real rendered sizes
    for some nodes (widget.py's relayout, re-laying out nodes that already
    have a live NodeItem) should pass a lookup that prefers those -- a
    node's stored label can be stale relative to what's actually on
    screen (a resolved/renamed function, live wrapping), so the estimate
    alone can under- or over-reserve space for an already-rendered node."""
    if not new_nodes:
        return
    size_of = size_of or _default_size

    new_ids = {n.id for n in new_nodes}
    internal_edges = [
        (e.src, e.dst)
        for e in canvas.edges.values()
        if e.src.id in new_ids and e.dst.id in new_ids
    ]

    if mode == "grid":
        positions = _layout_with_bfs_grid(new_nodes, internal_edges, size_of)
    elif mode == "dot":
        positions = _layout_with_dot(new_nodes, internal_edges, size_of)
    elif _dot_available():
        try:
            positions = _layout_with_dot(new_nodes, internal_edges, size_of)
        except Exception as exc:
            logger.warning("dot layout failed (%s), falling back to grid", exc)
            positions = _layout_with_bfs_grid(new_nodes, internal_edges, size_of)
    else:
        positions = _layout_with_bfs_grid(new_nodes, internal_edges, size_of)

    for node in new_nodes:
        if node.id not in positions:
            positions[node.id] = (0.0, 0.0)

    min_x = min(x for x, _ in positions.values())
    min_y = min(y for _, y in positions.values())

    bbox = _existing_bbox(canvas, exclude=new_ids, size_of=size_of)
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
