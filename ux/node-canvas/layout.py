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
_RANK_SPACING = 160.0
_COL_SPACING = 140.0


def _existing_bbox(canvas: Canvas, exclude: set[int]):
    xs = [n.x for n in canvas.nodes.values() if n.id not in exclude]
    ys = [n.y for n in canvas.nodes.values() if n.id not in exclude]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _dot_available() -> bool:
    return shutil.which("dot") is not None


def _layout_with_dot(new_nodes: list[Node], internal_edges) -> dict[int, tuple[float, float]]:
    lines = ["digraph G {"]
    for node in new_nodes:
        lines.append(f'  n{node.id} [label=""];')
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
        # node <name> <x> <y> <width> <height> ...
        name, x, y = parts[1], float(parts[2]), float(parts[3])
        node_id = int(name[1:])
        positions[node_id] = (x * _DOT_SCALE, y * _DOT_SCALE)
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

    positions = {}
    for rank, node_ids in by_rank.items():
        for col, node_id in enumerate(sorted(node_ids)):
            positions[node_id] = (col * _COL_SPACING, rank * _RANK_SPACING)
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
        _, _, max_x, _ = bbox
        offset_x = max_x + _COL_SPACING * 2 - min_x
        offset_y = -min_y

    logger.debug("canvas %r: laying out %d node(s), mode=%s", canvas.name, len(new_nodes), mode)
    with canvas.batch():
        for node in new_nodes:
            x, y = positions[node.id]
            canvas.set_node_position(node, x + offset_x, y + offset_y)
